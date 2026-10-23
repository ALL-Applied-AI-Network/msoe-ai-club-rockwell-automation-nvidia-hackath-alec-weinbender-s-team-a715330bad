import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Link, useNavigate } from "react-router";
import { api } from "../../../backend/client";
import { useCellProfile, useCompute, useMeta, usePart } from "../../../backend/queries";
import { SimBadge } from "../../../components/Badges";
import { Banner } from "../../../components/Banner";
import { Button } from "../../../components/Button";
import { Card } from "../../../components/Card";
import { NumberInput } from "../../../components/Field";
import { KeyValues } from "../../../components/KeyValues";
import { Table } from "../../../components/Table";
import { CAVEATS } from "../../../caveats";
import { degrees, dims, mass, mm } from "../../../format";
import { gpuSummary } from "../../../gpu";
import { paramLabel, searchMethodLabel, WIZARD_STEPS, wizardStep } from "../../../labels";
import { clearStoredDraft, useDraft } from "../draft";
import { capitalise, findPose, posesText, usePoses } from "../poses";
import { errorLabel, estimateText, taskLabel } from "../summary";
import styles from "../Wizard.module.css";

// How fast each way of running the Isaac sim server goes, for a typical job of about 12,100 grasps (frontend-plan.md,
// step 8; CONTEXT.md risk 7). The plan's estimate doesn't know the path yet (plan section 13).
const SIM_PATHS = [
  { path: "Reference", rate: "2.75 grasps/s", typical: "About 75 min", note: "The baseline" },
  { path: "CPU copies", rate: "About 5 grasps/s", typical: "About 40 min", note: "Matches the reference" },
  { path: "GPU copies", rate: "16 to 28 grasps/s", typical: "8 to 12 min", note: "Exploratory: holds about 9 of 81 more grasps" },
];

/** Raised when Run is refused because an input step blocks it: the step to send the user back to. */
class BlockedError extends Error {
  constructor(
    message: string,
    readonly step: number | null,
  ) {
    super(message);
  }
}

/** Step 8: one summary of every choice, each with a way back to its step; the plan the search will follow and what it
 *  costs; then Run. Run waits for a ready GPU and for every blocker to clear. */
export function ReviewStep() {
  const { draft, spec, plan, update } = useDraft();
  const meta = useMeta();
  const compute = useCompute();
  const part = usePart(draft.part_id);
  const poses = usePoses(draft.part_id);
  const ticked = draft.poses ?? [];
  const profile = useCellProfile(draft.cell_profile_id);
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const run = useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.POST("/api/jobs", { body: { ...spec!, duplicated_from: draft.duplicated_from ?? null } });
      if (data) return data;
      throw refusal(error, response);
    },
    onSuccess: (created) => {
      clearStoredDraft();
      void queryClient.invalidateQueries({ queryKey: ["jobs"] });
      navigate(`/jobs/${created.id}`);
    },
    onError: (error) => {
      const step = error instanceof BlockedError ? wizardStep(error.step) : undefined;
      if (step) navigate(`/new/${step.slug}`, { state: { runError: error.message } });
    },
  });

  const p = plan.data;
  const blockers = p?.blockers ?? [];
  const notReady = compute.data?.not_ready_reason;
  const canRun = spec != null && p != null && blockers.length === 0 && !notReady && !run.isPending;

  return (
    <>
      <dl className={styles.review}>
        <Row step={1} label="Name">
          {draft.name || "Named after the CAD file and today's date"}
        </Row>
        <Row step={1} label="Part">
          {part.data ? (
            [
              part.data.name,
              dims(part.data.extent_mm),
              meta.data?.materials.find((m) => m.name === part.data.material)?.label.toLowerCase() ?? "material not set",
              part.data.confirmed_mass_g == null
                ? "mass not known"
                : `${mass(part.data.confirmed_mass_g, part.data.mass_unit)} ${part.data.mass_source ?? "computed"}`,
            ].join(", ")
          ) : (
            <Missing>No part chosen</Missing>
          )}
        </Row>
        <Row step={2} label={ticked.length > 1 ? "Resting poses" : "Resting pose"}>
          {ticked.length > 0 && poses.data ? posesText(ticked, poses.data) : <Missing>No pose chosen</Missing>}
        </Row>
        <Row step={3} label="Task">
          {draft.task && meta.data ? taskLabel(draft.task, meta.data) : <Missing>No task chosen</Missing>}
        </Row>
        <Row step={4} label="Cell">
          {profile.data ? (
            <>
              {profile.data.name}, version {profile.data.version}
              {profile.data.twin_mismatches.length > 0 && ": results simulate the twin's gripper"}
            </>
          ) : (
            <Missing>No cell confirmed</Missing>
          )}
        </Row>
        <Row step={5} label="Grasp">
          {ticked.length > 0 && ticked.every((d) => d.grasp) ? (
            ticked.map(({ pose, grasp }) => (
              <span key={String(pose)} className={styles.line}>
                {ticked.length > 1 && `${capitalise(findPose(poses.data, pose)?.label ?? "pose")}: `}
                {ticked.length > 1 ? "jaws" : "Jaws"} close at {degrees(grasp!.angle_deg)}, {grasp!.source === "auto" ? "as proposed" : "picked by hand"};{" "}
                {grasp!.grip_height_mm != null ? `grip height fixed at ${mm(grasp!.grip_height_mm)}` : "the search chooses the grip height"}
              </span>
            ))
          ) : (
            <Missing>No grasp chosen</Missing>
          )}
        </Row>
        <Row step={6} label="Finger families">
          {p ? (
            p.families.map((f) => (
              <span key={f.family} className={styles.line}>
                {f.label}: {f.free.length === 0 ? "one design, every parameter fixed" : `${f.free.length} free parameters: ${f.free.map((name) => paramLabel(name).toLowerCase()).join(", ")}`}
              </span>
            ))
          ) : (
            <Missing>Shown once the plan is worked out</Missing>
          )}
        </Row>
        <Row step={7} label="Camera error">
          {draft.error && meta.data ? (
            <>
              {errorLabel(draft.error, meta.data)}
              {p && `; ${p.totals.search_offsets} offsets per design while searching, ${p.totals.final_offsets} in the final test`}
            </>
          ) : (
            <Missing>No camera error set</Missing>
          )}
        </Row>
      </dl>

      {blockers.length > 0 && (
        <Banner tone="bad" title="Can't run yet">
          <span className={styles.list}>
            {blockers.map((b) => (
              <span key={`${b.step}-${b.reason}`}>
                {b.reason} <Link to={`/new/${WIZARD_STEPS[b.step - 1]?.slug ?? "part"}`}>Fix in step {b.step}</Link>
              </span>
            ))}
          </span>
        </Banner>
      )}
      {p && p.warnings.length > 0 && (
        <Banner tone="warn" title="Warnings">
          <span className={styles.list}>
            {p.warnings.map((w) => (
              <span key={w}>{w}</span>
            ))}
          </span>
        </Banner>
      )}

      <Card title="The plan">
        {p ? (
          <>
            <Table
              label="The searches"
              rowKey={(s) => s.key}
              rows={p.searches}
              columns={[
                { key: "family", header: "Search", render: (s) => p.families.find((f) => f.family === s.family)?.label ?? s.family },
                { key: "method", header: "Method", render: (s) => searchMethodLabel(s.method) },
                { key: "budget", header: "Designs", align: "right", render: (s) => s.budget.toLocaleString() },
                { key: "batch", header: "Per round", align: "right", render: (s) => s.batch_size },
              ]}
            />
            <KeyValues
              items={[
                { label: "Designs", value: (p.totals.search_designs + p.totals.final_designs).toLocaleString() },
                { label: "Grasps", value: p.totals.total_grasps.toLocaleString() },
                { label: "Rounds", value: String(p.totals.rounds) },
                {
                  label: "Estimate",
                  value: p.estimate.seconds == null ? "Unknown until runs on this sim have measured it" : estimateText(p.estimate.seconds),
                },
              ]}
            />
            <details className={styles.advanced}>
              <summary>Speed of each sim path</summary>
              <Table
                label="Speed of each sim path"
                rowKey={(row) => row.path}
                rows={SIM_PATHS}
                columns={[
                  { key: "path", header: "Path", render: (row) => row.path },
                  { key: "rate", header: "Rate", render: (row) => row.rate },
                  { key: "typical", header: "A typical job", render: (row) => row.typical },
                  { key: "note", header: "Results", render: (row) => row.note },
                ]}
              />
            </details>
          </>
        ) : (
          <p className={styles.note}>
            {plan.error ? `The plan couldn't be worked out: ${plan.error.message}` : spec ? "Working out the plan" : "The plan needs every step above."}
          </p>
        )}
      </Card>

      <Card title="What it runs on">
        <div className={styles.runsOn}>
          {p && <SimBadge backend={p.sim_backend} />}
          {compute.data && <span>{gpuSummary(compute.data).text}</span>}
        </div>
        {p?.sim_backend === "mock" && <p className={styles.note}>{CAVEATS.mock}</p>}
        <details className={styles.advanced}>
          <summary>Advanced</summary>
          <div className={styles.fields}>
            <NumberInput
              label="Seed"
              step={1}
              min={0}
              value={draft.seed}
              onChange={(seed) => update({ seed: seed == null ? 0 : Math.round(seed) })}
              hint="The same seed and inputs repeat the same search."
            />
          </div>
        </details>
      </Card>

      <div className={styles.run}>
        {notReady && (
          <p className={styles.reason}>
            {notReady} <Link to="/gpu">Connect a GPU</Link>
          </p>
        )}
        {run.error && !(run.error instanceof BlockedError && run.error.step) && <Banner tone="bad">{run.error.message}</Banner>}
        <Button disabled={!canRun} onClick={() => run.mutate()}>
          {run.isPending ? "Starting" : "Run the experiment"}
        </Button>
      </div>
    </>
  );
}

/** One choice on the review list, with a way back to its step. */
function Row({ step, label, children }: { step: number; label: string; children: ReactNode }) {
  return (
    <div className={styles.reviewRow}>
      <dt>{label}</dt>
      <dd>{children}</dd>
      <Link to={`/new/${WIZARD_STEPS[step - 1].slug}`} className={styles.edit} aria-label={`Edit ${label.toLowerCase()}`}>
        Edit
      </Link>
    </div>
  );
}

function Missing({ children }: { children: ReactNode }) {
  return <span className={styles.missing}>{children}</span>;
}

/** The API's refusal as an Error: a blocked spec (422 with the step to fix), no GPU (409), or anything else. */
function refusal(error: unknown, response: Response): Error {
  const detail = typeof error === "object" && error !== null && "detail" in error ? (error as { detail: unknown }).detail : undefined;
  if (typeof detail === "object" && detail !== null && "message" in detail) {
    const { message, failed_step } = detail as { message: string; failed_step?: number | null };
    return new BlockedError(message, failed_step ?? null);
  }
  if (typeof detail === "string") return new Error(detail);
  if (Array.isArray(detail)) return new Error(detail.map((d) => (d as { msg?: string }).msg ?? JSON.stringify(d)).join("; "));
  return new Error(`${response.status} ${response.statusText}`);
}
