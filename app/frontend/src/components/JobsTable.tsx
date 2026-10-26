import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { api, unwrap, type Schemas } from "../backend/client";
import { meshUrl, useMeta } from "../backend/queries";
import { designLabel, JOB_KINDS } from "../labels";
import { duration, of, percent, timeAgo } from "../format";
import { CAVEATS } from "../caveats";
import { canResume, isActive, JobStatusBadge } from "./Badges";
import { LinkButton } from "./Button";
import { ConfirmDialog } from "./ConfirmDialog";
import { Menu, type MenuItem } from "./Menu";
import { PartViewer } from "./PartViewer";
import { ProgressBar } from "./ProgressBar";
import { Score } from "./Score";
import { Table, type Column } from "./Table";
import styles from "./JobsTable.module.css";

type Job = Schemas["JobCard"];
type Part = Schemas["PartResponse"];

type JobsTableProps = {
  jobs: Job[];
  parts: Part[] | undefined; // for each job's part number and thumbnail
  variant: "active" | "completed" | "all"; // which columns: work under way, results, or both in one list
  label: string; // what the table lists, for screen readers
  empty?: string;
};

/** Jobs of both kinds, one per row: the part, the stage, the status, how far along or what came out, and the grasp
 *  success. The overview's two tables and the job list. */
export function JobsTable({ jobs, parts, variant, label, empty }: JobsTableProps) {
  const meta = useMeta();
  const byId = new Map(parts?.map((p) => [p.id, p]));
  const task = (job: Job) => meta.data?.task_kinds.find((t) => t.name === job.task_kind)?.label ?? job.task_kind;

  const part: Column<Job> = { key: "part", header: "Part", width: "27%", render: (job) => <PartCell job={job} part={byId.get(job.part_id)} /> };
  const stage: Column<Job> = {
    key: "type",
    header: "Type",
    width: "20%",
    render: (job) => <Lines main={JOB_KINDS[job.kind ?? "generation"]} sub={task(job)} />,
  };
  const status: Column<Job> = {
    key: "status",
    header: "Status",
    width: "13%",
    render: (job) => (
      <div className={styles.status}>
        <JobStatusBadge status={job.status} />
        {!isActive(job.status) && <span className={styles.sub}>{timeAgo(job.finished ?? job.created)}</span>}
      </div>
    ),
  };
  const progress: Column<Job> = { key: "progress", header: "Progress", width: "16%", render: (job) => <Progress job={job} /> };
  const elapsed: Column<Job> = { key: "elapsed", header: "Elapsed", width: "13%", render: (job) => <Elapsed job={job} /> };
  const quality: Column<Job> = {
    key: "quality",
    header: "Grasp success",
    width: "15%",
    render: (job) =>
      isActive(job.status) ? (
        <Score value={job.best_value} look="dot" sub={job.best_value != null ? "Best so far" : undefined} />
      ) : (
        <Score value={job.winner?.success} sub={job.winner && job.sim_backend === "mock" ? <MockNote /> : undefined} />
      ),
  };
  const result: Column<Job> = { key: "result", header: "Result", width: "20%", render: (job) => <Result job={job} /> };
  const action: Column<Job> = {
    key: "action",
    header: "Action",
    width: "120px",
    render: (job) => (
      <LinkButton size="sm" variant="secondary" to={`/jobs/${job.id}`}>
        {job.status === "done" ? (job.kind === "evaluation" ? "View ranking" : "View design") : "Open"}
      </LinkButton>
    ),
  };
  const menu: Column<Job> = { key: "menu", header: "", render: (job) => <JobMenu job={job} />, width: "44px" };

  const columns =
    variant === "active"
      ? [part, stage, status, progress, elapsed, quality, menu]
      : variant === "completed"
        ? [part, stage, status, result, quality, menu] // compact: the name opens the job, the menu has the rest
        : [part, stage, status, { ...result, header: "Progress or result", render: (job: Job) => (isActive(job.status) ? <Progress job={job} /> : <Result job={job} />) }, quality, action, menu];

  return <Table columns={columns} rows={jobs} rowKey={(job) => job.id} label={label} empty={empty} fixed />;
}

function PartCell({ job, part }: { job: Job; part: Part | undefined }) {
  const name = part?.part_number ?? job.part_name ?? "Unknown part";
  return (
    <div className={styles.part}>
      <PartViewer mode="icon" url={meshUrl(job.part_id)} label={job.part_name ?? "The part"} />
      <div className={styles.lines}>
        <Link to={`/jobs/${job.id}`} className={styles.title} title={name}>
          {name}
        </Link>
        <span className={styles.sub} title={job.name}>
          {job.name}
        </span>
        <span className={styles.id}>{job.batch_id ? `${job.experiment_id}, batch` : job.experiment_id}</span>
      </div>
    </div>
  );
}

/** A cell's main line and the line under it, each kept to one line; the full text shows on hover. */
function Lines({ main, sub }: { main: string; sub?: string }) {
  return (
    <div className={styles.lines}>
      <span className={styles.main} title={main}>
        {main}
      </span>
      {sub && (
        <span className={styles.sub} title={sub}>
          {sub}
        </span>
      )}
    </div>
  );
}

/** Under a result from the mock sim: it's geometry only, never a prediction. */
function MockNote() {
  return (
    <span className={styles.mock} title={CAVEATS.mock}>
      Mock sim
    </span>
  );
}

function Progress({ job }: { job: Job }) {
  const fraction = job.n_total ? job.n_done / job.n_total : 0;
  return (
    <div className={styles.progress}>
      <span className={styles.main}>{job.status === "queued" ? "Waiting" : percent(fraction)}</span>
      <ProgressBar value={fraction} label="Progress" tone="active" />
    </div>
  );
}

/** How long a running job has been going, ticking every second, and where it's got to. */
function Elapsed({ job }: { job: Job }) {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    if (!isActive(job.status)) return;
    const timer = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(timer);
  }, [job.status]);
  if (job.status === "queued") return <Lines main="Not started" />;
  const step = job.kind === "evaluation" ? "Sim request" : "Round";
  return <Lines main={duration(now - job.created)} sub={job.status === "finalizing" ? "Final test" : `${step} ${of(job.round, job.n_rounds)}`} />;
}

/** What a finished job came to: the best finger, or the designed one; or where it stopped. */
function Result({ job }: { job: Job }) {
  if (job.status === "done" && job.winner) {
    const best =
      job.kind === "evaluation"
        ? { main: "Best existing finger", sub: `${job.winner.label}, ${percent(job.winner.success)} success` }
        : { main: "Generated finger", sub: `${designLabel(job.winner.label)} predicted ${percent(job.winner.success)}` };
    return <Lines main={best.main} sub={job.stock ? `${best.sub}, stock ${percent(job.stock.success)}` : best.sub} />;
  }
  if (job.status === "failed") return <Lines main="Failed" sub={job.failure ?? undefined} />;
  if (canResume(job.status)) return <Lines main="Stopped" sub={job.n_done > 0 ? `at ${of(job.round, job.n_rounds)}` : "nothing finished"} />;
  return <Lines main="No result" />;
}

/** A job's other actions: open, cancel (asks first), resume, duplicate, and what follows from a finished one. */
function JobMenu({ job }: { job: Job }) {
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
  const evaluation = job.kind === "evaluation";
  const items: MenuItem[] = [
    { label: "Open", to: `/jobs/${job.id}` },
    ...(isActive(job.status) ? [{ label: "Cancel", danger: true, onSelect: () => setConfirming(true) }] : []),
    ...(canResume(job.status)
      ? [{ label: resume.isPending ? "Resuming" : "Resume", disabled: resume.isPending, title: resume.error?.message, onSelect: () => resume.mutate() }]
      : []),
    { label: "Duplicate", to: evaluation ? `/evaluate?from=${job.id}` : `/new/part?from=${job.id}` },
    ...(job.status === "done" && evaluation ? [{ label: "Generate a new finger", to: `/new/part?generate=${job.id}` }] : []),
    ...(job.status === "done" && !evaluation ? [{ label: "Physical validation", to: `/jobs/${job.id}/validation` }] : []),
  ];
  return (
    <>
      <Menu label={`More for ${job.experiment_id}`} items={items} />
      <ConfirmDialog
        open={confirming && isActive(job.status)}
        title={`Cancel ${job.experiment_id}?`}
        confirmLabel="Cancel the job"
        cancelLabel="Keep running"
        danger
        pending={cancel.isPending}
        error={cancel.error?.message}
        onConfirm={() => cancel.mutate()}
        onClose={() => setConfirming(false)}
      >
        It stops after the current step. Everything done so far is kept, and Resume continues from there.
      </ConfirmDialog>
    </>
  );
}
