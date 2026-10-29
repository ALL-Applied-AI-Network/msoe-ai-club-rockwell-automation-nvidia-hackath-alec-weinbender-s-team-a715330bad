import { useState } from "react";
import { useParams } from "react-router";
import { JobStatusBadge, PhysicalBadge, SimBadge } from "../../components/Badges";
import { LinkButton } from "../../components/Button";
import { Page } from "../../components/Page";
import { EmptyState, ErrorState, Skeleton } from "../../components/States";
import { Tabs } from "../../components/Tabs";
import { LogStage } from "./LogStage";
import { PrintedFingersStage } from "./PrintedFingersStage";
import { PrintSelectionStage } from "./PrintSelectionStage";
import { ReviewStage } from "./ReviewStage";
import { usePrintedFingers, usePrintSelection, useResults, useTestPlans, useJob, useValidation } from "./queries";
import { PredictionStage, TestPlanStage } from "./TestPlanStage";
import styles from "./JobValidationPage.module.css";

/** #/jobs/:id/validation: one experiment's physical validation, in six stages. Print the chosen designs, record the
 *  printed fingers, approve them for the robot, plan the trials, let the sim predict them, then log them at the robot and compare. */
export function JobValidationPage() {
  const { id = "" } = useParams();
  const job = useJob(id);
  const done = job.data?.status === "done";
  const results = useResults(id, done);
  const selection = usePrintSelection(id, done);
  const fingers = usePrintedFingers(id, done);
  const plans = useTestPlans(id, done);
  const validation = useValidation(id, done);
  const [planId, setPlanId] = useState<number | null>(null);

  if (job.isPending) {
    return (
      <Page title="Physical validation">
        <Skeleton height={320} />
      </Page>
    );
  }
  if (job.isError) {
    return (
      <Page title="Physical validation">
        <ErrorState title="Couldn't load the experiment" message={job.error.message} onRetry={() => job.refetch()} />
      </Page>
    );
  }

  const detail = job.data;
  const header = (
    <>
      <div className={styles.badges}>
        <JobStatusBadge status={detail.status} />
        <SimBadge backend={detail.sim_backend} />
        <PhysicalBadge status={detail.card.physical_badge} />
      </div>
      <Tabs
        label="This experiment"
        tabs={[
          { to: `/jobs/${id}`, label: done ? "Results" : "Progress", end: true },
          { to: `/jobs/${id}/validation`, label: "Validation" },
        ]}
      />
    </>
  );
  // Test plans, predictions and logged trials cover the primary pose only, for now
  const primary = detail.plan.poses.length > 1 ? detail.plan.poses[0].label : null;
  const title = `${detail.name} (${detail.experiment_id})`;
  const back = (
    <>
      <LinkButton variant="secondary" to="/validation">
        All validation
      </LinkButton>
      <LinkButton variant="primary" to={`/jobs/${id}`}>
        Back to the experiment
      </LinkButton>
    </>
  );

  if (!done) {
    return (
      <Page title={title} description="Physical validation" actions={back}>
        {header}
        <EmptyState
          title="Validation starts once the experiment is done"
          action={
            <LinkButton variant="secondary" to="/jobs">
              Back to the jobs
            </LinkButton>
          }
        >
          This experiment is {detail.card.status}.
        </EmptyState>
      </Page>
    );
  }

  const loading = [results, selection, fingers, plans, validation].find((q) => q.isPending);
  const failed = [results, selection, fingers, plans, validation].find((q) => q.isError);
  const finalTable = results.data?.final_table ?? [];
  const chosen = selection.data?.designs ?? [];
  const baselines = ["IMP", "STOCK"].filter((label) => selection.data?.available.includes(label));
  const printable = (selection.data?.available ?? []).filter((label) => label !== "STOCK");
  const planList = plans.data ?? [];
  const current = planList.find((p) => p.id === planId) ?? planList.at(-1);
  const task = detail.spec.task.kind;

  return (
    <Page title={title} description="Physical validation" actions={back}>
      {header}
      {loading && <Skeleton height={320} />}
      {failed?.error && (
        <ErrorState title="Couldn't load the validation data" message={failed.error.message} onRetry={() => failed.refetch()} />
      )}
      {primary && <p className={styles.note}>Validated {primary} only: the other resting poses aren't tested on the robot yet.</p>}
      {!loading && !failed && selection.data && (
        <div className={styles.stages}>
          <PrintSelectionStage jobId={id} finalTable={finalTable} selection={selection.data} />
          <PrintedFingersStage
            jobId={id}
            toPrint={[...chosen, ...baselines.filter((label) => label !== "STOCK")]}
            printable={printable}
            fingers={fingers.data ?? []}
          />
          <ReviewStage jobId={id} experimentId={detail.experiment_id} review={detail.review} />
          <TestPlanStage
            jobId={id}
            designs={[...chosen, ...baselines]}
            plans={planList}
            current={current}
            onChoose={setPlanId}
          />
          <PredictionStage jobId={id} plan={current} />
          <LogStage
            jobId={id}
            experimentId={detail.experiment_id}
            plan={current}
            needsTolerance={task === "place" || task === "insert"}
            review={detail.review}
            validation={validation.data}
            simBackend={detail.sim_backend}
          />
        </div>
      )}
    </Page>
  );
}
