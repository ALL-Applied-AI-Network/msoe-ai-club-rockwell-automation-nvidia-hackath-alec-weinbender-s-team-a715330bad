import { useMutation } from "@tanstack/react-query";
import { api, unwrap, type Schemas } from "../../backend/client";
import { Banner } from "../../components/Banner";
import { LinkButton } from "../../components/Button";
import { DownloadButton } from "../../components/DownloadButton";
import { FileDrop } from "../../components/FileDrop";
import { ProgressBar } from "../../components/ProgressBar";
import { Stat } from "../../components/Stat";
import { Table, type Column } from "../../components/Table";
import { of } from "../../format";
import { Comparison } from "./Comparison";
import { useRefreshJob } from "./queries";
import { Stage } from "./Stage";
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

/** Stage 5: run the plan at the robot, log the outcomes through the spreadsheet, and compare them with the sim. */
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

  return (
    <Stage
      step={5}
      title="Log the trials and compare"
      status={STATUS[validation?.badge ?? "none"]}
      description="Run the plan at the robot, fill in the spreadsheet, and upload it."
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
              The review is part of the experiment's results page.
            </Banner>
          )}

          <div className={styles.panel}>
            <h3 className={styles.panelTitle}>At the robot</h3>
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
              <LinkButton variant="ghost" size="sm" to={`/jobs/${jobId}/log`}>
                Or log one trial at a time on a phone
              </LinkButton>
            </div>
            <div className={styles.progressRow}>
              <span className={styles.note}>
                {of(plan.logged, plan.planned)} trials logged
                {plan.extras ? `, plus ${plan.extras} extra` : ""}
              </span>
              <ProgressBar value={plan.planned ? plan.logged / plan.planned : 0} label="Trials logged" />
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
