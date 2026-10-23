import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { api, unwrap, type Schemas } from "../../backend/client";
import { canResume, isActive, JobStatusBadge, PhysicalBadge, SimBadge } from "../../components/Badges";
import { Button, LinkButton } from "../../components/Button";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { ProgressBar } from "../../components/ProgressBar";
import { of, percent, timeAgo } from "../../format";
import { isReconnecting } from "../../gpu";
import { wizardStep } from "../../labels";
import { useInView, useJobEvents } from "./useJobEvents";
import styles from "./JobRow.module.css";

type Job = Schemas["JobCard"];
type Compute = Schemas["ComputeStatusResponse"];

type JobRowProps = {
  job: Job;
  taskLabel: string;
  compute: Compute | undefined;
  live: boolean; // follow the job over SSE while it runs; false when the page polls the whole list instead
};

/** One experiment in the Experiments list: what it is, where it got to, and what to do next. */
export function JobRow({ job, taskLabel, compute, live }: JobRowProps) {
  const { ref, inView } = useInView<HTMLDivElement>();
  useJobEvents(job.id, live && inView && isActive(job.status));

  const queryClient = useQueryClient();
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["jobs"] });
  const [confirming, setConfirming] = useState(false);
  const cancel = useMutation({
    mutationFn: () => unwrap(api.POST("/api/jobs/{job_id}/cancel", { params: { path: { job_id: job.id } } })),
    onSuccess: () => setConfirming(false),
    onSettled: refresh,
  });
  const resume = useMutation({
    mutationFn: () => unwrap(api.POST("/api/jobs/{job_id}/resume", { params: { path: { job_id: job.id } } })),
    onSettled: refresh,
  });

  const active = isActive(job.status);
  const waiting = active && isReconnecting(compute?.session);
  const notReady = compute?.not_ready_reason;
  const fixStep = wizardStep(job.failed_step);
  const hasDetail =
    job.status === "failed" || waiting || (canResume(job.status) && Boolean(notReady)) || Boolean(resume.error);

  return (
    <div ref={ref} className={styles.row}>
      <div className={styles.name}>
        <Link to={`/jobs/${job.id}`} className={styles.title}>
          {job.name}
        </Link>
        <code className={styles.id}>{job.experiment_id}</code>
      </div>

      <div className={styles.part}>
        <span className={styles.value}>{job.part_name ?? "Unknown part"}</span>
        <span className={styles.sub}>{taskLabel}</span>
      </div>

      <div className={styles.badges}>
        <JobStatusBadge status={job.status} />
        {job.physical_badge !== "none" && <PhysicalBadge status={job.physical_badge} />}
      </div>

      <div className={styles.result}>
        <Result job={job} waiting={waiting} />
      </div>

      <span className={styles.time} title={new Date((job.finished ?? job.created) * 1000).toLocaleString()}>
        {job.finished ? `Finished ${timeAgo(job.finished)}` : `Started ${timeAgo(job.created)}`}
      </span>

      <div className={styles.actions}>
        {active && (
          <Button variant="ghost" size="sm" onClick={() => setConfirming(true)}>
            Cancel
          </Button>
        )}
        {canResume(job.status) && (
          <Button
            variant="ghost"
            size="sm"
            disabled={Boolean(notReady) || resume.isPending}
            title={notReady ?? "Continue after the last finished round"}
            onClick={() => resume.mutate()}
          >
            Resume
          </Button>
        )}
        {job.status === "done" && (
          <LinkButton variant="ghost" size="sm" to={`/jobs/${job.id}/validation`}>
            Validate
          </LinkButton>
        )}
        <LinkButton variant="ghost" size="sm" to={`/new/part?from=${job.id}`}>
          Duplicate
        </LinkButton>
        <LinkButton variant="secondary" size="sm" to={`/jobs/${job.id}`}>
          Open
        </LinkButton>
      </div>

      {hasDetail && (
        <div className={styles.detail}>
          {job.status === "failed" && <p className={styles.failure}>{job.failure ?? "The job failed."}</p>}
          {job.status === "failed" && fixStep && (
            <LinkButton size="sm" to={`/new/${fixStep.slug}?from=${job.id}`}>
              Fix in step {job.failed_step}: {fixStep.label}
            </LinkButton>
          )}
          {waiting && <p className={styles.waiting}>Waiting for the GPU connection. The job continues once it's back.</p>}
          {canResume(job.status) && notReady && (
            <p className={styles.note}>
              Resume needs a ready GPU. <Link to="/gpu">Connect a GPU</Link>
            </p>
          )}
          {resume.error && <p className={styles.failure}>{resume.error.message}</p>}
        </div>
      )}

      <ConfirmDialog
        open={confirming && active} // closes by itself if the job finishes while it's open
        title={`Cancel ${job.experiment_id}?`}
        confirmLabel="Cancel the experiment"
        cancelLabel="Keep running"
        danger
        pending={cancel.isPending}
        error={cancel.error?.message}
        onConfirm={() => cancel.mutate()}
        onClose={() => setConfirming(false)}
      >
        It stops after the current round. Everything done so far is kept, and Resume continues from there.
      </ConfirmDialog>
    </div>
  );
}

/** The result column: the winner against the stock fingers once done, progress while running, where it stopped. The sim
 *  badge sits next to the number when the number came from the mock, since that number isn't a prediction. */
function Result({ job, waiting }: { job: Job; waiting: boolean }) {
  const mock = job.sim_backend === "mock" && <SimBadge backend="mock" />;
  if (isActive(job.status)) {
    return (
      <>
        <ProgressBar value={job.n_total ? job.n_done / job.n_total : 0} label="Designs evaluated" tone={waiting ? "warn" : "acc"} />
        <span className={styles.sub}>
          {job.status === "queued"
            ? "Starting"
            : job.status === "finalizing"
              ? "Final test"
              : `Round ${of(job.round, job.n_rounds)}`}
          {job.best_value != null && `, best ${percent(job.best_value)}`}
        </span>
      </>
    );
  }
  if (job.status === "done") {
    if (!job.winner) return <span className={styles.sub}>No winner</span>;
    return (
      <div className={styles.score}>
        <span className={styles.best}>{percent(job.winner.success)}</span>
        {job.stock && <span className={styles.sub}>stock {percent(job.stock.success)}</span>}
        {mock}
      </div>
    );
  }
  if (canResume(job.status) && job.n_done > 0) {
    return (
      <span className={styles.sub}>
        Stopped at round {of(job.round, job.n_rounds)}
        {job.best_value != null && `, best ${percent(job.best_value)}`}
      </span>
    );
  }
  return <span className={styles.sub}>No rounds finished</span>;
}
