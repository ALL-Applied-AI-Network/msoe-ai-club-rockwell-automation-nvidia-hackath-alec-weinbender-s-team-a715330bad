import { useSearchParams } from "react-router";
import type { Schemas } from "../../backend/client";
import { useJobs, useParts } from "../../backend/queries";
import { canResume, isActive } from "../../components/Badges";
import { LinkButton } from "../../components/Button";
import { Card } from "../../components/Card";
import { FilterBar } from "../../components/FilterBar";
import { Icon } from "../../components/Icon";
import { JobsTable } from "../../components/JobsTable";
import { Page } from "../../components/Page";
import { SearchInput } from "../../components/SearchInput";
import { Segmented } from "../../components/Segmented";
import { Select } from "../../components/Select";
import { ErrorState, Skeleton } from "../../components/States";
import { matches } from "../overview/OverviewPage";

type Job = Schemas["JobCard"];

const STATUS = {
  all: { label: "All", test: () => true },
  running: { label: "Running", test: (job: Job) => isActive(job.status) },
  done: { label: "Done", test: (job: Job) => job.status === "done" },
  stopped: { label: "Stopped or failed", test: (job: Job) => canResume(job.status) },
} as const;
type Status = keyof typeof STATUS;

/** #/jobs: every job of both types (evaluation and generation), newest first. The filters live in the address, so Back returns to the same view. */
export function JobsPage() {
  const jobs = useJobs();
  const parts = useParts();
  const [params, setParams] = useSearchParams();
  const status = (params.get("status") ?? "all") as Status;
  const type = params.get("type") ?? ""; // a job's type: evaluation or generation (the API calls it kind)
  const batch = params.get("batch") ?? "";
  const query = params.get("q") ?? "";
  const set = (key: string, value: string) =>
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
  const scoped = all.filter((job) => (!type || job.kind === type) && (!batch || job.batch_id === batch) && matches(job, parts.data, query));
  const shown = scoped.filter(STATUS[status]?.test ?? (() => true));

  return (
    <Page
      title="Jobs"
      description="Evaluations of the finger library and finger generation runs"
      actions={
        <>
          <LinkButton variant="secondary" to="/new/part">
            <Icon name="bolt" />
            Generate a finger
          </LinkButton>
          <LinkButton variant="primary" to="/evaluate">
            <Icon name="plus" />
            New evaluation
          </LinkButton>
        </>
      }
    >
      <FilterBar
        chips={
          <Segmented
            label="Status"
            value={status}
            onChange={(value) => set("status", value === "all" ? "" : value)}
            options={Object.entries(STATUS).map(([value, f]) => ({ value: value as Status, label: f.label, count: scoped.filter(f.test).length }))}
          />
        }
      >
        <Select
          label="Type"
          inline
          value={type}
          onChange={(event) => set("type", event.target.value)}
          options={[
            { value: "", label: "All types" },
            { value: "evaluation", label: "Evaluations" },
            { value: "generation", label: "Generations" },
          ]}
        />
        <SearchInput value={query} onChange={(value) => set("q", value)} placeholder="Search by part number, name or ID" />
      </FilterBar>

      {jobs.isPending && <Skeleton height={320} />}
      {jobs.isError && <ErrorState title="Couldn't load the jobs" message={jobs.error.message} onRetry={() => jobs.refetch()} />}
      {jobs.isSuccess && (
        <Card title={batch ? "Jobs in this batch" : "All jobs"} subtitle={`${shown.length} of ${all.length}`} flush>
          <JobsTable jobs={shown} parts={parts.data} variant="all" label="Jobs" empty="No jobs match these filters." />
        </Card>
      )}
    </Page>
  );
}
