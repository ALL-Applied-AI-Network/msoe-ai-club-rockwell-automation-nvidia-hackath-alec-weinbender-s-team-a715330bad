import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router";
import { api, unwrap, type Schemas } from "../../backend/client";
import { useCompute, useMeta } from "../../backend/queries";
import { canResume, isActive } from "../../components/Badges";
import { Button, LinkButton } from "../../components/Button";
import { Icon } from "../../components/Icon";
import { Page } from "../../components/Page";
import { Segmented } from "../../components/Segmented";
import { Select } from "../../components/Select";
import { EmptyState, ErrorState, Skeleton } from "../../components/States";
import { JobCard } from "./JobCard";
import styles from "./ExperimentsPage.module.css";

type Job = Schemas["JobCard"];

// Up to this many running jobs, each card follows its own SSE stream. Past it, the page polls the list instead.
const MAX_STREAMS = 6;

const STATUS_FILTERS = {
  all: { label: "All", test: () => true },
  running: { label: "Running", test: (job: Job) => isActive(job.status) },
  done: { label: "Done", test: (job: Job) => job.status === "done" },
  stopped: { label: "Stopped or failed", test: (job: Job) => canResume(job.status) },
} as const;
type StatusFilter = keyof typeof STATUS_FILTERS;

/** Home: every experiment, newest first, with running ones updating live. */
export function ExperimentsPage() {
  const meta = useMeta();
  const compute = useCompute();
  const jobs = useQuery({
    queryKey: ["jobs"],
    queryFn: () => unwrap(api.GET("/api/jobs")),
    refetchInterval: (query) => (running(query.state.data) > MAX_STREAMS ? 3_000 : 15_000),
  });

  // Filters live in the URL, so Back from an experiment returns to the same view.
  const [params, setParams] = useSearchParams();
  const status = (params.get("status") ?? "all") as StatusFilter;
  const part = params.get("part") ?? "";
  const sim = params.get("sim") ?? "";
  const oldestFirst = params.get("sort") === "oldest";
  const setParam = (key: string, value: string) =>
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        if (value) next.set(key, value);
        else next.delete(key);
        return next;
      },
      { replace: true },
    );

  const all = jobs.data ?? [];
  const inScope = all.filter((job) => (!part || job.part_id === part) && (!sim || job.sim_backend === sim));
  const shown = inScope
    .filter(STATUS_FILTERS[status]?.test ?? (() => true))
    .sort((a, b) => (oldestFirst ? a.created - b.created : b.created - a.created));
  const parts = [...new Map(all.map((job) => [job.part_id, job.part_name ?? job.part_id])).entries()];
  const taskLabel = (kind: Job["task_kind"]) => meta.data?.task_kinds.find((t) => t.name === kind)?.label ?? kind;
  const live = running(all) <= MAX_STREAMS;

  return (
    <Page
      title="Experiments"
      description="Every finger search you've run. Running ones update live, and keep running when you close the page."
      actions={
        <LinkButton variant="primary" to="/new/part">
          <Icon name="plus" />
          New experiment
        </LinkButton>
      }
    >
      {all.length > 0 && (
        <div className={styles.toolbar}>
          <Segmented
            label="Status"
            value={status}
            onChange={(value) => setParam("status", value === "all" ? "" : value)}
            options={Object.entries(STATUS_FILTERS).map(([value, filter]) => ({
              value: value as StatusFilter,
              label: filter.label,
              count: inScope.filter(filter.test).length,
            }))}
          />
          <div className={styles.selects}>
            <Select
              label="Part"
              value={part}
              onChange={(event) => setParam("part", event.target.value)}
              options={[{ value: "", label: "All parts" }, ...parts.map(([value, label]) => ({ value, label }))]}
            />
            <Select
              label="Simulator"
              value={sim}
              onChange={(event) => setParam("sim", event.target.value)}
              options={[
                { value: "", label: "All simulators" },
                { value: "isaac", label: "Isaac Sim" },
                { value: "mock", label: "Mock sim" },
              ]}
            />
            <Select
              label="Order"
              value={oldestFirst ? "oldest" : ""}
              onChange={(event) => setParam("sort", event.target.value)}
              options={[
                { value: "", label: "Newest first" },
                { value: "oldest", label: "Oldest first" },
              ]}
            />
          </div>
        </div>
      )}

      {jobs.isPending && (
        <div className={styles.grid}>
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} height={260} />
          ))}
        </div>
      )}
      {jobs.isError && (
        <ErrorState title="Couldn't load the experiments" message={jobs.error.message} onRetry={() => jobs.refetch()} />
      )}
      {jobs.isSuccess && all.length === 0 && (
        <EmptyState
          title="No experiments yet"
          action={
            <LinkButton variant="primary" to="/new/part">
              New experiment
            </LinkButton>
          }
        >
          Upload a part, choose a task, and the app searches for fingers that pick it up even when the camera is off.
        </EmptyState>
      )}
      {jobs.isSuccess && all.length > 0 && shown.length === 0 && (
        <EmptyState
          title="No experiments match these filters"
          action={
            <Button variant="secondary" onClick={() => setParams({}, { replace: true })}>
              Clear the filters
            </Button>
          }
        />
      )}
      {shown.length > 0 && (
        <div className={styles.grid}>
          {shown.map((job) => (
            <JobCard key={job.id} job={job} taskLabel={taskLabel(job.task_kind)} compute={compute.data} live={live} />
          ))}
        </div>
      )}
    </Page>
  );
}

function running(jobs: Job[] | undefined): number {
  return jobs?.filter((job) => isActive(job.status)).length ?? 0;
}
