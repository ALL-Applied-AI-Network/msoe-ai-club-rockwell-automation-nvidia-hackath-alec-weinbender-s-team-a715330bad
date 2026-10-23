import { meshUrl, useCellProfile, useMeta, usePart } from "../../backend/queries";
import { PartViewer } from "../../components/PartViewer";
import { Stat } from "../../components/Stat";
import { degrees, dims, mm } from "../../format";
import { useDraft } from "./draft";
import { findPose, posesText, usePoses } from "./poses";
import { errorLabel, estimateText, taskLabel } from "./summary";
import styles from "./Wizard.module.css";

/** The wizard's summary rail: the part, the key choices so far, and the live run estimate once there's a plan. */
export function SummaryRail() {
  const { draft, plan } = useDraft();
  const meta = useMeta();
  const part = usePart(draft.part_id);
  const profile = useCellProfile(draft.cell_profile_id);
  const poses = usePoses(draft.part_id);
  const ticked = draft.poses ?? [];

  const items: { label: string; value: string }[] = [];
  if (part.data) {
    items.push({ label: "Part", value: part.data.name });
    items.push({ label: "Size", value: dims(part.data.extent_mm) });
    if (ticked.length > 0 && poses.data) items.push({ label: "Resting", value: posesText(ticked, poses.data) });
  }
  if (draft.task && meta.data) items.push({ label: "Task", value: taskLabel(draft.task, meta.data) });
  if (profile.data) items.push({ label: "Cell", value: `${profile.data.name}, version ${profile.data.version}` });
  for (const { pose, grasp } of ticked) {
    if (!grasp) continue;
    items.push({
      label: ticked.length > 1 ? `Grasp, ${findPose(poses.data, pose)?.label ?? "pose"}` : "Grasp",
      value: `Jaws close at ${degrees(grasp.angle_deg)}, ${grasp.source === "auto" ? "proposed" : "picked by hand"}`,
    });
  }
  if (draft.families?.length && meta.data)
    items.push({
      label: "Finger families",
      value: draft.families.map((f) => meta.data.families.find((m) => m.name === f.family)?.label ?? f.family).join(", "),
    });
  if (draft.error && meta.data) items.push({ label: "Camera error", value: errorLabel(draft.error, meta.data) });

  const estimate = plan.data?.estimate;
  const totals = plan.data?.totals;

  return (
    <div className={styles.rail}>
      <section className={styles.railSection} aria-label="Summary">
        {part.data ? (
          <PartViewer
            url={meshUrl(part.data.id, ticked[0]?.pose)}
            label={`${part.data.name}, ${findPose(poses.data, ticked[0]?.pose ?? "as_authored")?.label ?? "as uploaded"}`}
            mode="thumbnail"
          />
        ) : (
          <p className={styles.note}>No part chosen yet.</p>
        )}
        {items.length > 0 && <Facts items={items} />}
      </section>
      <section className={styles.railSection} aria-label="Run estimate">
        {estimate && totals ? (
          <>
            <Stat
              size="lg"
              label="Run estimate"
              value={estimateText(estimate.seconds)}
              detail={
                estimate.seconds == null
                  ? "Unknown until runs on this sim have measured it"
                  : `${rate(estimate.grasps_per_s)} grasps per second, ${estimate.source === "measured" ? "measured" : "as configured"}`
              }
            />
            <Facts
              items={[
                { label: "Grasps", value: totals.total_grasps.toLocaleString() },
                { label: "Rounds", value: String(totals.rounds) },
                { label: "Designs", value: totals.search_designs.toLocaleString() },
                { label: "Offsets per design", value: String(totals.search_offsets) },
                ...(draft.error && plan.data ? [{ label: "Furthest offset", value: mm(Math.max(...plan.data.grid.radii_mm)) }] : []),
              ]}
            />
            {plan.isFetching && <p className={styles.note}>Updating</p>}
          </>
        ) : (
          <p className={styles.note}>
            {plan.error ? `The plan couldn't be worked out: ${plan.error.message}` : "Run estimate after the grasp step."}
          </p>
        )}
      </section>
    </div>
  );
}

/** Label and value on one row each: the rail is too narrow for KeyValues' grid. */
function Facts({ items }: { items: { label: string; value: string }[] }) {
  return (
    <dl className={styles.facts}>
      {items.map((item) => (
        <div key={item.label} className={styles.fact}>
          <dt>{item.label}</dt>
          <dd>{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

function rate(graspsPerS: number | null): string {
  return graspsPerS == null ? "Unknown" : graspsPerS >= 100 ? Math.round(graspsPerS).toLocaleString() : graspsPerS.toFixed(1);
}
