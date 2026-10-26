import { useState } from "react";
import { Link } from "react-router";
import type { Schemas } from "../../backend/client";
import { useCompute, useJobs, useMeta, useParts } from "../../backend/queries";
import { isActive, SimBadge } from "../../components/Badges";
import { Card } from "../../components/Card";
import { FilterBar } from "../../components/FilterBar";
import { Icon, type IconName } from "../../components/Icon";
import { JobsTable } from "../../components/JobsTable";
import { Segmented } from "../../components/Segmented";
import { SearchInput } from "../../components/SearchInput";
import { ErrorState, Skeleton } from "../../components/States";
import { Page } from "../../components/Page";
import { percent, timeAgo } from "../../format";
import { gpuSummary } from "../../gpu";
import { JOB_KINDS } from "../../labels";
import styles from "./OverviewPage.module.css";

type Job = Schemas["JobCard"];
type Part = Schemas["PartResponse"];

const RECENT = 5; // finished jobs in the overview's second table
const ACTIVITY = 5;

const FILTERS = {
  all: { label: "All", test: () => true },
  running: { label: "Running", test: (job: Job) => job.status === "running" || job.status === "finalizing" },
  queued: { label: "Queued", test: (job: Job) => job.status === "queued" },
} as const;
type Filter = keyof typeof FILTERS;

/** Home: what's running on the sim, what just finished, the GPU, and the next things to do. */
export function OverviewPage() {
  const jobs = useJobs();
  const parts = useParts();
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");

  const all = jobs.data ?? [];
  const found = all.filter((job) => matches(job, parts.data, query));
  const active = found.filter((job) => isActive(job.status) && FILTERS[filter].test(job));
  const finished = filter === "all" ? found.filter((job) => !isActive(job.status)).slice(0, RECENT) : [];

  const rail = (
    <>
      <ComputeCard jobs={all} />
      <QuickActions />
      <Activity jobs={all} parts={parts.data ?? []} />
    </>
  );

  return (
    <Page title="Overview" description="Simulation progress and grasp results" rail={rail}>
      <FilterBar
        chips={
          <Segmented
            label="Show"
            value={filter}
            onChange={setFilter}
            options={Object.entries(FILTERS).map(([value, f]) => ({
              value: value as Filter,
              label: f.label,
              count: value === "all" ? all.length : all.filter(f.test).length,
            }))}
          />
        }
      >
        <SearchInput value={query} onChange={setQuery} placeholder="Search by part number, name or ID" />
      </FilterBar>

      {jobs.isPending && <Skeleton height={280} />}
      {jobs.isError && <ErrorState title="Couldn't load the jobs" message={jobs.error.message} onRetry={() => jobs.refetch()} />}
      {jobs.isSuccess && (
        <>
          <Card title="Active jobs" more={{ to: "/jobs?status=running", label: "View all" }} flush>
            <JobsTable jobs={active} parts={parts.data} variant="active" label="Active jobs" empty="Nothing is running. Start an evaluation or generate a finger." />
          </Card>
          {filter === "all" && (
            <Card title="Recently completed" more={{ to: "/jobs", label: "View all" }} flush>
              <JobsTable jobs={finished} parts={parts.data} variant="completed" label="Recently completed jobs" empty="No finished jobs yet." />
            </Card>
          )}
        </>
      )}
    </Page>
  );
}

/** Whether a job matches the search: its part's number or name, its own name, or its experiment ID. */
export function matches(job: Job, parts: Part[] | undefined, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  const part = parts?.find((p) => p.id === job.part_id);
  return [job.name, job.experiment_id, job.part_name, part?.part_number, part?.name].some((text) => text?.toLowerCase().includes(q));
}

function ComputeCard({ jobs }: { jobs: Job[] }) {
  const compute = useCompute();
  const meta = useMeta();
  const gpu = compute.data && gpuSummary(compute.data);
  const running = jobs.filter((job) => job.status === "running" || job.status === "finalizing").length;
  const queued = jobs.filter((job) => job.status === "queued").length;
  return (
    <Card title="Compute" icon="chip" more={{ to: "/gpu", label: "GPU page" }}>
      <div className={styles.facts}>
        <div className={styles.fact}>
          <span className={styles.factLabel}>GPU</span>
          <span className={`${styles.factValue} ${styles[gpu?.tone ?? "neutral"]}`}>{gpu?.text ?? "Checking"}</span>
        </div>
        <div className={styles.fact}>
          <span className={styles.factLabel}>Simulator</span>
          {meta.data && <SimBadge backend={meta.data.sim.badge} />}
        </div>
      </div>
      <div className={styles.counts}>
        <div>
          <span className={styles.factLabel}>Active jobs</span>
          <span className={styles.count}>{running}</span>
        </div>
        <div>
          <span className={styles.factLabel}>Queued jobs</span>
          <span className={styles.count}>{queued}</span>
        </div>
      </div>
    </Card>
  );
}

const ACTIONS: { to: string; icon: IconName; title: string; text: string }[] = [
  { to: "/evaluate", icon: "plus-box", title: "New part evaluation", text: "Rank the library on a part" },
  { to: "/parts?upload=1", icon: "cloud", title: "Upload parts", text: "One CAD file or a whole folder" },
  { to: "/new/part", icon: "bolt", title: "Generate a finger", text: "Design a new finger for a part" },
];

function QuickActions() {
  return (
    <Card title="Quick actions" icon="bolt">
      <div className={styles.actions}>
        {ACTIONS.map((action) => (
          <Link key={action.to} to={action.to} className={styles.action}>
            <span className={styles.actionIcon}>
              <Icon name={action.icon} />
            </span>
            <span className={styles.actionText}>
              <span className={styles.actionTitle}>{action.title}</span>
              <span className={styles.actionSub}>{action.text}</span>
            </span>
            <Icon name="chevron" />
          </Link>
        ))}
      </div>
    </Card>
  );
}

type Event = { key: string; at: number; tone: "ok" | "active" | "neutral" | "bad"; title: string; sub: string; to: string };

/** The latest things that happened, from the jobs and the parts: finished, failed, started, queued, uploaded. */
function Activity({ jobs, parts }: { jobs: Job[]; parts: Part[] }) {
  const events: Event[] = [
    ...jobs.map((job): Event => {
      const kind = job.kind === "evaluation" ? "Evaluation" : "Generation";
      const to = `/jobs/${job.id}`;
      const part = job.part_name ?? job.experiment_id;
      if (job.status === "done")
        return { key: job.id, at: job.finished ?? job.created, tone: "ok", title: `${kind} completed`, sub: job.winner ? `${part}, ${percent(job.winner.success)}` : part, to };
      if (job.status === "failed") return { key: job.id, at: job.finished ?? job.created, tone: "bad", title: `${kind} failed`, sub: part, to };
      if (isActive(job.status))
        return { key: job.id, at: job.created, tone: job.status === "queued" ? "neutral" : "active", title: `${job.experiment_id} ${job.status === "queued" ? "queued" : "running"}`, sub: JOB_KINDS[job.kind ?? "generation"], to };
      return { key: job.id, at: job.finished ?? job.created, tone: "neutral", title: `${kind} stopped`, sub: part, to };
    }),
    ...parts.map((part): Event => ({ key: part.id, at: part.created, tone: "neutral", title: "Part uploaded", sub: part.part_number ?? part.name, to: `/parts/${part.id}` })),
  ]
    .sort((a, b) => b.at - a.at)
    .slice(0, ACTIVITY);

  return (
    <Card title="Recent activity" icon="clock" more={{ to: "/jobs", label: "View all" }}>
      {events.length === 0 ? (
        <p className={styles.quiet}>Nothing yet.</p>
      ) : (
        <ul className={styles.activity}>
          {events.map((event) => (
            <li key={event.key}>
              <Link to={event.to} className={styles.event}>
                <span className={`${styles.eventDot} ${styles[event.tone]}`} aria-hidden="true" />
                <span className={styles.eventText}>
                  <span className={styles.eventTitle}>{event.title}</span>
                  <span className={styles.eventSub}>{event.sub}</span>
                </span>
                <span className={styles.eventTime}>{timeAgo(event.at)}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
