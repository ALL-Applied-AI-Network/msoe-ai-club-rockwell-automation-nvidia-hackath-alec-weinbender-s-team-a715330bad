import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { api, unwrap, type Schemas } from "../../backend/client";
import { canResume, isActive, JobStatusBadge, PhysicalBadge, SimBadge } from "../../components/Badges";
import { Button, LinkButton } from "../../components/Button";
import { Card } from "../../components/Card";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { ProgressBar } from "../../components/ProgressBar";
import { Stat } from "../../components/Stat";
import { CAVEATS } from "../../caveats";
import { mm, of, percent, timeAgo } from "../../format";
import { isReconnecting } from "../../gpu";
import { designLabel, wizardStep } from "../../labels";
import { useInView, useJobEvents } from "./useJobEvents";
import styles from "./JobCard.module.css";

type Job = Schemas["JobCard"];
type Compute = Schemas["ComputeStatusResponse"];

type JobCardProps = {
  job: Job;
  taskLabel: string;
  compute: Compute | undefined;
  live: boolean; // follow the job over SSE while it runs; false when the page polls the whole list instead
};

/** One experiment on the Experiments page: what it is, where it got to, and what to do next. */
export function JobCard({ job, taskLabel, compute, live }: JobCardProps) {
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
  const notReady = compute?.not_ready_reason;
  const fixStep = wizardStep(job.failed_step);

  return (
    <div ref={ref} className={styles.wrap}>
      <Card
        title={<Link to={`/jobs/${job.id}`}>{job.name}</Link>}
        subtitle={<code>{job.experiment_id}</code>}
        aside={<JobStatusBadge status={job.status} />}
        footer={
          <>
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
          </>
        }
      >
        <dl className={styles.facts}>
          <div>
            <dt>Part</dt>
            <dd>{job.part_name ?? "Unknown part"}</dd>
          </div>
          <div>
            <dt>Task</dt>
            <dd>{taskLabel}</dd>
          </div>
        </dl>
        <div className={styles.badges}>
          <SimBadge backend={job.sim_backend} />
          <PhysicalBadge status={job.physical_badge} />
        </div>

        <div className={styles.status}>
          {active && <Progress job={job} waiting={isReconnecting(compute?.session)} />}
          {job.status === "done" && <Outcome job={job} />}
          {job.status === "failed" && (
            <>
              <p className={styles.failure}>{job.failure ?? "The job failed."}</p>
              {fixStep && (
                <div>
                  <LinkButton size="sm" to={`/new/${fixStep.slug}?from=${job.id}`}>
                    Fix in step {job.failed_step}: {fixStep.label}
                  </LinkButton>
                </div>
              )}
            </>
          )}
          {job.status === "cancelled" && <p className={styles.note}>Cancelled. Resume continues from its last round.</p>}
          {job.status === "interrupted" && (
            <p className={styles.note}>
              The worker stopped, for example the laptop slept or restarted. Resume continues after the last finished
              round.
            </p>
          )}
          {canResume(job.status) && job.n_done > 0 && (
            <p className={styles.note}>
              Stopped after round {of(job.round, job.n_rounds)}, with {of(job.n_done, job.n_total)} designs evaluated
              {job.best_value != null && `, best ${percent(job.best_value)}`}.
            </p>
          )}
          {canResume(job.status) && notReady && (
            <p className={styles.note}>
              Resume needs a ready GPU. <Link to="/gpu">Connect a GPU</Link>
            </p>
          )}
          {resume.error && <p className={styles.failure}>{resume.error.message}</p>}
          {job.sim_backend === "mock" && (active || job.status === "done") && <p className={styles.caveat}>{CAVEATS.mock}</p>}
        </div>
      </Card>
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
        It stops after the round it's on now finishes. Everything done so far is kept, and Resume continues from there.
      </ConfirmDialog>
    </div>
  );
}

function Progress({ job, waiting }: { job: Job; waiting: boolean }) {
  return (
    <>
      <div className={styles.stats}>
        <Stat label="Round" value={of(job.round, job.n_rounds)} />
        <Stat label="Designs" value={of(job.n_done, job.n_total)} />
        <Stat label="Best so far" value={job.best_value == null ? "None yet" : percent(job.best_value)} tone="acc" />
      </div>
      <ProgressBar value={job.n_total ? job.n_done / job.n_total : 0} label="Designs evaluated" tone={waiting ? "warn" : "acc"} />
      {job.status === "queued" && <p className={styles.note}>The worker is starting.</p>}
      {job.status === "finalizing" && (
        <p className={styles.note}>Final test: the top designs and the baselines, re-tested on the dense grid.</p>
      )}
      {waiting && (
        <p className={styles.waiting}>Waiting for the GPU connection. The job carries on by itself once it's back.</p>
      )}
    </>
  );
}

function Outcome({ job }: { job: Job }) {
  if (!job.winner) return <p className={styles.note}>Done. Open it for the results.</p>;
  const capture = (radius: number | null) => (radius == null ? "no capture radius" : `capture radius ${mm(radius)}`);
  return (
    <div className={styles.outcome}>
      <Stat
        size="lg"
        tone="acc"
        label={`Best design, ${designLabel(job.winner.label)}`}
        value={percent(job.winner.success)}
        detail={capture(job.winner.capture_radius_mm)}
      />
      {job.stock && (
        <Stat
          size="lg"
          label="Stock fingers"
          value={percent(job.stock.success)}
          detail={capture(job.stock.capture_radius_mm)}
        />
      )}
    </div>
  );
}
