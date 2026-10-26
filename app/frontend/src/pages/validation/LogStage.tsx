import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { api, unwrap, type Schemas } from "../../backend/client";
import { Banner } from "../../components/Banner";
import { DownloadButton } from "../../components/DownloadButton";
import { FileDrop } from "../../components/FileDrop";
import { ProgressBar } from "../../components/ProgressBar";
import { Segmented } from "../../components/Segmented";
import { ErrorState, Skeleton } from "../../components/States";
import { Stat } from "../../components/Stat";
import { Table, type Column } from "../../components/Table";
import { of } from "../../format";
import { Comparison } from "./Comparison";
import { useRefreshJob, useTestPlan } from "./queries";
import { Stage } from "./Stage";
import { TrialLogger } from "./TrialLogger";
import styles from "./JobValidationPage.module.css";

type Plan = Schemas["TestPlanSummaryResponse"];
type Validation = Schemas["Validation"];
type Review = Schemas["Review"];
type RowError = Schemas["RowError"];

const ERROR_COLUMNS: Column<RowError>[] = [
  { key: "row", header: "Row", align: "right", sortValue: (e) => e.row, render: (e) => e.row },
  { key: "trial", header: "Trial", render: (e) => <code>{e.trial_id ?? "none"}</code> },
  { key: "reason", header: "Why it wasn't applied", render: (e) => e.reason },
];

const STATUS = {
  none: { tone: "neutral", label: "Nothing logged yet" },
  in_progress: { tone: "active", label: "In progress" },
  validated: { tone: "ok", label: "Validated" },
} as const;

/** Stage 6: run the plan at the robot, log the outcomes (one trial at a time at the robot, or the filled-in spreadsheet),
 *  and compare them with the sim. */
export function LogStage({
  jobId,
  experimentId,
  plan,
  needsTolerance,
  review,
  validation,
  simBackend,
}: {
  jobId: string;
  experimentId: string;
  plan: Plan | undefined;
  needsTolerance: boolean; // place and insert: the operator also fills in_tolerance
  review: Review | null | undefined;
  validation: Validation | undefined;
  simBackend: "mock" | "isaac";
}) {
  const refresh = useRefreshJob(jobId);
  const upload = useMutation({
    mutationFn: ({ planId, file }: { planId: number; file: File }) =>
      unwrap(
        api.POST("/api/jobs/{job_id}/test-plans/{plan_id}/upload", {
          params: { path: { job_id: jobId, plan_id: planId } },
          body: { file: file as unknown as string }, // the schema types the multipart file as a string
          bodySerializer: (body) => {
            const form = new FormData();
            form.append("file", body.file as unknown as File);
            return form;
          },
        }),
      ),
    onSettled: refresh,
  });
  const base = `/api/jobs/${encodeURIComponent(jobId)}/test-plans/${plan?.id}`;
  const approved = review?.status === "approved";
  const [mode, setMode] = useState<"one" | "sheet">("one");

  return (
    <Stage
      step={6}
      title="Log the trials and compare"
      status={STATUS[validation?.badge ?? "none"]}
      description="Run the plan at the robot and log each trial: one at a time as you go, or in the spreadsheet."
    >
      {!plan ? (
        <p className={styles.note}>Create a test plan first.</p>
      ) : (
        <>
          {!approved && (
            <Banner tone="warn" title="Not approved for the robot yet">
              {review?.status === "rejected"
                ? `A reviewer rejected these fingers${review.reviewer ? ` (${review.reviewer})` : ""}${review.notes ? `: ${review.notes}` : "."} `
                : "No printed finger goes on the real arm until a named reviewer approves it. "}
              Approve them in stage 3 first.
            </Banner>
          )}

          <div className={styles.progressRow}>
            <span className={styles.note}>
              {of(plan.logged, plan.planned)} trials logged in plan {plan.id}
              {plan.extras ? `, plus ${plan.extras} extra` : ""}
            </span>
            <ProgressBar value={plan.planned ? plan.logged / plan.planned : 0} label="Trials logged" />
          </div>
          <Segmented
            label="How to log"
            value={mode}
            onChange={setMode}
            options={[
              { value: "one", label: "One trial at a time" },
              { value: "sheet", label: "Upload the spreadsheet" },
            ]}
          />

          {mode === "one" ? (
            <OneAtATime jobId={jobId} planId={plan.id} tolerance={needsTolerance} />
          ) : (
            <>
              <div className={styles.panel}>
                <ol className={styles.steps}>
                  <li>Download plan {plan.id}. The spreadsheet's prediction column is hidden, so the operator tests blind.</li>
                  <li>
                    Command each trial's offset on the robot. Don't move the part: it stays where it always is, and the
                    offset is what the fingers are designed to tolerate.
                  </li>
                  <li>
                    Fill in <code>outcome</code> with held, missed or skipped
                    {needsTolerance ? ", and in_tolerance with whether the part landed within the task's tolerance" : ""}.
                    Notes and a video link are optional.
                  </li>
                  <li>Upload the filled-in spreadsheet here.</li>
                </ol>
                <div className={styles.actions}>
                  <DownloadButton href={`${base}.xlsx`} label={`Download plan ${plan.id} (.xlsx)`} />
                  <DownloadButton href={`${base}.csv`} label="Download as .csv" />
                </div>
              </div>

              <FileDrop
                label={`Drop the filled-in plan ${plan.id} here`}
                accept=".xlsx,.csv"
                busy={upload.isPending ? "Reading the spreadsheet" : undefined}
                error={upload.error?.message}
                hint="Uploading again keeps earlier outcomes."
                onFile={(file) => upload.mutate({ planId: plan.id, file })}
              />
            </>
          )}

          {upload.data && (
            <div className={styles.panel} role="status">
              <h3 className={styles.panelTitle}>Upload report</h3>
              <div className={styles.stats}>
                <Stat label="Accepted" value={upload.data.accepted} />
                <Stat label="Extra trials" value={upload.data.extras} detail="Rows without a trial ID" />
                <Stat label="Unchanged" value={upload.data.unchanged} />
                <Stat label="Still pending" value={upload.data.pending} detail="Rows with no outcome yet" />
              </div>
              {upload.data.errors.length > 0 && (
                <>
                  <p className={styles.note}>
                    These rows weren't applied; the rest were. Fix them and upload the file again.
                  </p>
                  <Table
                    label="Rows that weren't applied"
                    columns={ERROR_COLUMNS}
                    rows={upload.data.errors}
                    rowKey={(e) => `${e.row}-${e.trial_id ?? ""}`}
                    rowTone={() => "bad"}
                  />
                </>
              )}
            </div>
          )}
        </>
      )}

      {validation && (
        <Comparison jobId={jobId} experimentId={experimentId} validation={validation} simBackend={simBackend} />
      )}
    </Stage>
  );
}

/** The plan's trials, logged one at a time at the robot. */
function OneAtATime({ jobId, planId, tolerance }: { jobId: string; planId: number; tolerance: boolean }) {
  const plan = useTestPlan(jobId, planId);
  if (plan.isPending) return <Skeleton height={320} />;
  if (plan.isError) return <ErrorState title="Couldn't load the test plan" message={plan.error.message} onRetry={() => void plan.refetch()} />;
  return <TrialLogger key={planId} jobId={jobId} planId={planId} rows={plan.data.rows} logged={plan.data.logged_trials} tolerance={tolerance} />;
}
