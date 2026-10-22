import { useState } from "react";
import { useParams } from "react-router";
import { JobStatusBadge, PhysicalBadge, SimBadge } from "../../components/Badges";
import { LinkButton } from "../../components/Button";
import { Page } from "../../components/Page";
import { EmptyState, ErrorState, Skeleton } from "../../components/States";
import { LogStage } from "./LogStage";
import { PrintedFingersStage } from "./PrintedFingersStage";
import { PrintSelectionStage } from "./PrintSelectionStage";
import { usePrintedFingers, usePrintSelection, useResults, useTestPlans, useJob, useValidation } from "./queries";
import { PredictionStage, TestPlanStage } from "./TestPlanStage";
import styles from "./JobValidationPage.module.css";

/** #/jobs/:id/validation: one experiment's physical validation, in five stages. Print the chosen designs, record the
 *  printed fingers, plan the trials, let the sim predict them, then log them at the robot and compare. */
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
    <div className={styles.badges}>
      <JobStatusBadge status={detail.status} />
      <SimBadge backend={detail.sim_backend} />
      <PhysicalBadge status={detail.card.physical_badge} />
    </div>
  );
  const title = `${detail.name} (${detail.experiment_id})`;
  const back = (
    <LinkButton variant="secondary" to="/validation">
      All validation
    </LinkButton>
  );

  if (!done) {
    return (
      <Page title={title} description="Physical validation" actions={back}>
        {header}
        <EmptyState
          title="Validation starts once the experiment is done"
          action={
            <LinkButton variant="secondary" to="/">
              Back to the experiments
            </LinkButton>
          }
        >
          The final test labels the designs (D1, D2, and so on) that get printed and tested. This experiment is{" "}
          {detail.card.status}.
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
    <Page
      title={title}
      description="Print the best designs, test them on the robot against the stock fingers and the imprint, and see how far the sim's predictions hold."
      actions={back}
    >
      {header}
      {loading && <Skeleton height={320} />}
      {failed?.error && (
        <ErrorState title="Couldn't load the validation data" message={failed.error.message} onRetry={() => failed.refetch()} />
      )}
      {!loading && !failed && selection.data && (
        <div className={styles.stages}>
          <PrintSelectionStage jobId={id} finalTable={finalTable} selection={selection.data} />
          <PrintedFingersStage
            jobId={id}
            toPrint={[...chosen, ...baselines.filter((label) => label !== "STOCK")]}
            printable={printable}
            fingers={fingers.data ?? []}
          />
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
