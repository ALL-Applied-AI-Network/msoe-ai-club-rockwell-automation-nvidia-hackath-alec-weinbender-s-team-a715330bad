import { meshUrl, useCellProfile, useMeta, usePart } from "../../backend/queries";
import { Card } from "../../components/Card";
import { KeyValues, type KeyValue } from "../../components/KeyValues";
import { PartViewer } from "../../components/PartViewer";
import { Stat } from "../../components/Stat";
import { degrees, dims, mm } from "../../format";
import { useDraft } from "./draft";
import { errorLabel, estimateText, taskLabel } from "./summary";
import styles from "./Wizard.module.css";

/** The wizard's summary rail: the part, the key choices so far, and the live run estimate once there's a plan. */
export function SummaryRail() {
  const { draft, plan } = useDraft();
  const meta = useMeta();
  const part = usePart(draft.part_id);
  const profile = useCellProfile(draft.cell_profile_id);

  const items: KeyValue[] = [];
  if (part.data) {
    items.push({ label: "Part", value: part.data.name });
    items.push({ label: "Size", value: dims(part.data.extent_mm) });
    if (part.data.pose) items.push({ label: "Resting", value: part.data.pose.label });
  }
  if (draft.task && meta.data) items.push({ label: "Task", value: taskLabel(draft.task, meta.data) });
  if (profile.data) items.push({ label: "Cell", value: `${profile.data.name}, version ${profile.data.version}` });
  if (draft.grasp)
    items.push({
      label: "Grasp",
      value: `Jaws close at ${degrees(draft.grasp.angle_deg)}, ${draft.grasp.source === "auto" ? "proposed" : "picked by hand"}`,
    });
  if (draft.families?.length && meta.data)
    items.push({
      label: "Finger families",
      value: draft.families.map((f) => meta.data.families.find((m) => m.name === f.family)?.label ?? f.family).join(", "),
    });
  if (draft.error && meta.data) items.push({ label: "Camera error", value: errorLabel(draft.error, meta.data) });

  const estimate = plan.data?.estimate;
  const totals = plan.data?.totals;

  return (
    <>
      <Card title="Summary">
        {part.data ? (
          <PartViewer url={meshUrl(part.data.id)} label={`${part.data.name}, ${part.data.pose?.label ?? "as uploaded"}`} mode="thumbnail" />
        ) : (
          <p className={styles.note}>No part chosen yet.</p>
        )}
        {items.length > 0 && <KeyValues items={items} />}
      </Card>
      <Card title="Run estimate">
        {estimate && totals ? (
          <>
            <Stat
              size="lg"
              label="Time"
              value={estimateText(estimate.seconds)}
              detail={
                estimate.seconds == null
                  ? "Unknown until runs on this sim have measured it"
                  : estimate.source === "measured"
                    ? `At ${rate(estimate.grasps_per_s)} grasps per second, measured on this sim`
                    : `At ${rate(estimate.grasps_per_s)} grasps per second, as configured`
              }
            />
            <KeyValues
              items={[
                { label: "Grasps", value: totals.total_grasps.toLocaleString() },
                { label: "Rounds", value: String(totals.rounds) },
                { label: "Designs searched", value: totals.search_designs.toLocaleString() },
                { label: "Offsets per design", value: String(totals.search_offsets) },
              ]}
            />
            {plan.isFetching && <p className={styles.note}>Updating</p>}
          </>
        ) : (
          <p className={styles.note}>
            {plan.error ? `The plan couldn't be worked out: ${plan.error.message}` : "Estimate after the grasp step."}
          </p>
        )}
        {draft.error && plan.data && (
          <p className={styles.note}>Tested at offsets up to {mm(Math.max(...plan.data.grid.radii_mm))} from centre.</p>
        )}
      </Card>
    </>
  );
}

function rate(graspsPerS: number | null): string {
  return graspsPerS == null ? "an unknown" : graspsPerS >= 100 ? Math.round(graspsPerS).toLocaleString() : graspsPerS.toFixed(1);
}
