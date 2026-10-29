import { useQueries, useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { api, unwrap, type Schemas } from "../../backend/client";
import { PhysicalBadge, SimBadge } from "../../components/Badges";
import { BackButton } from "../../components/BackButton";
import { Banner } from "../../components/Banner";
import { LinkButton } from "../../components/Button";
import { Card } from "../../components/Card";
import { ParityScatter, type ParityPoint } from "../../components/charts/ParityScatter";
import { Page } from "../../components/Page";
import { EmptyState, ErrorState, Skeleton } from "../../components/States";
import { Table, type Column } from "../../components/Table";
import { CAVEATS } from "../../caveats";
import { count, percent, timeAgo } from "../../format";
import { designLabel } from "../../labels";
import { jobKey } from "./queries";
import styles from "./ValidationPage.module.css";

type Job = Schemas["JobCard"];
type DesignValidation = Schemas["DesignValidation"];

const DESIGN_COLUMNS: Column<DesignValidation>[] = [
  { key: "design", header: "Design", render: (d) => <strong className={styles.design}>{designLabel(d.design_label)}</strong> },
  {
    key: "predicted",
    header: "Predicted",
    align: "right",
    render: (d) => (d.predicted_success == null ? "none" : percent(d.predicted_success)),
  },
  {
    key: "measured",
    header: "Measured",
    align: "right",
    render: (d) => (d.measured_success == null ? "none yet" : percent(d.measured_success)),
  },
  { key: "agreement", header: "Agreement", render: (d) => d.summary },
];

/** #/validation: how far the sim's predictions hold on the real robot, across every experiment with physical trials,
 *  and which finished experiments are ready to validate. */
export function ValidationPage() {
  const jobs = useQuery({ queryKey: ["jobs"], queryFn: () => unwrap(api.GET("/api/jobs")) });
  const all = jobs.data ?? [];
  const tested = all.filter((job) => job.physical_badge !== "none");
  const ready = all.filter((job) => job.status === "done" && job.physical_badge === "none");
  const notDone = all.length - tested.length - ready.length;
  // No endpoint covers every experiment yet (plan, section 13), so each tested experiment's validation is fetched.
  const validations = useQueries({
    queries: tested.map((job) => ({
      queryKey: [...jobKey(job.id), "validation"],
      queryFn: () => unwrap(api.GET("/api/jobs/{job_id}/validation", { params: { path: { job_id: job.id } } })),
    })),
  });

  const points: ParityPoint[] = tested.flatMap((job, i) =>
    (validations[i]?.data?.designs ?? [])
      .filter((d) => d.predicted_success != null && d.measured_success != null)
      .map((d) => ({
        key: `${job.id}-${d.design_label}`,
        title: `${job.experiment_id}, ${designLabel(d.design_label)}`,
        predicted: d.predicted_success!,
        measured: d.measured_success!,
        low: d.wilson_low,
        high: d.wilson_high,
        n: d.n,
      })),
  );
  const anyMock = tested.some((job) => job.sim_backend === "mock");
  const close = points.filter((p) => p.low != null && p.high != null && p.predicted >= p.low && p.predicted <= p.high).length;

  return (
    <Page title="Validation" actions={<BackButton />}>
      {jobs.isPending && <Skeleton height={360} />}
      {jobs.isError && <ErrorState title="Couldn't load the experiments" message={jobs.error.message} onRetry={() => jobs.refetch()} />}

      {jobs.isSuccess && tested.length === 0 && ready.length === 0 && (
        <EmptyState
          title="Nothing to validate yet"
          action={
            <LinkButton variant="secondary" to="/">
              Experiments
            </LinkButton>
          }
        >
          Finished experiments show up here, ready to print and test on the robot.
          {notDone > 0 && ` ${count(notDone, "experiment is", "experiments are")} still running or stopped.`}
        </EmptyState>
      )}

      {jobs.isSuccess && (tested.length > 0 || ready.length > 0) && (
        <>
          {points.length > 0 && (
            <section className={styles.section}>
              <h2 className={styles.heading}>Sim against the robot</h2>
              <Card>
                {anyMock && <Banner tone="warn">{CAVEATS.mock} Some predictions here come from the mock sim.</Banner>}
                <div className={styles.parity}>
                  <ParityScatter
                    points={points}
                    summary={`Predicted against measured success for ${count(points.length, "design", "designs")} across ${count(tested.length, "experiment", "experiments")}. ${close} of ${points.length} predictions fall inside the measured 95% interval.`}
                    note="Each dot is one design, with the 95% interval of its measured rate. Above the diagonal the robot did better than predicted, below it worse."
                  />
                  <p className={styles.callout}>
                    <strong>{close} of {points.length}</strong> predictions fall inside the measured 95% interval.
                  </p>
                </div>
              </Card>
            </section>
          )}

          {ready.length > 0 && (
            <section className={styles.section}>
              <h2 className={styles.heading}>Ready to validate</h2>
              <Table label="Experiments ready to validate" columns={READY_COLUMNS} rows={ready} rowKey={(job) => job.id} />
            </section>
          )}

          {tested.length > 0 && (
            <section className={styles.section}>
              <h2 className={styles.heading}>Tested on the robot</h2>
              <div className={styles.grid}>
                {tested.map((job, i) => (
                  <TestedCard key={job.id} job={job} designs={validations[i]?.data?.designs} error={validations[i]?.error?.message} />
                ))}
              </div>
            </section>
          )}

          {notDone > 0 && (
            <p className={styles.note}>{count(notDone, "other experiment is", "other experiments are")} still running or stopped.</p>
          )}
        </>
      )}
    </Page>
  );
}

function TestedCard({ job, designs, error }: { job: Job; designs: DesignValidation[] | undefined; error?: string }) {
  return (
    <Card
      title={<Link to={`/jobs/${job.id}/validation`}>{job.name}</Link>}
      subtitle={<code>{job.experiment_id}</code>}
      aside={<PhysicalBadge status={job.physical_badge} />}
      footer={
        <>
          <span className={styles.note}>{job.part_name ?? "Unknown part"}</span>
          <LinkButton size="sm" to={`/jobs/${job.id}/validation`} className={styles.push}>
            Open
          </LinkButton>
        </>
      }
    >
      <div>
        <SimBadge backend={job.sim_backend} />
      </div>
      {error && <p className={styles.error}>{error}</p>}
      {designs ? (
        <Table label={`${job.experiment_id} designs`} columns={DESIGN_COLUMNS} rows={designs} rowKey={(d) => d.design_label} />
      ) : (
        !error && <Skeleton height={140} />
      )}
    </Card>
  );
}

const READY_COLUMNS: Column<Job>[] = [
  {
    key: "name",
    header: "Experiment",
    sortValue: (job) => job.name,
    render: (job) => (
      <span className={styles.experiment}>
        <span className={styles.design}>{job.name}</span>
        <code>{job.experiment_id}</code>
      </span>
    ),
  },
  { key: "part", header: "Part", render: (job) => job.part_name ?? "Unknown part" },
  { key: "sim", header: "Simulator", render: (job) => <SimBadge backend={job.sim_backend} /> },
  {
    key: "winner",
    header: "Best design",
    align: "right",
    sortValue: (job) => job.winner?.success,
    render: (job) => (job.winner ? `${designLabel(job.winner.label)}, ${percent(job.winner.success)}` : "none"),
  },
  { key: "finished", header: "Finished", sortValue: (job) => job.finished, render: (job) => (job.finished ? timeAgo(job.finished) : "") },
  {
    key: "start",
    header: "",
    align: "right",
    render: (job) => (
      <LinkButton size="sm" to={`/jobs/${job.id}/validation`}>
        Validate
      </LinkButton>
    ),
  },
];
