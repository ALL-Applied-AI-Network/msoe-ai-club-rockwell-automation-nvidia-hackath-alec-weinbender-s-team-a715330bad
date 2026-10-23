import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { api, unwrap, type Schemas } from "../../backend/client";
import { useCompute } from "../../backend/queries";
import { Badge, type Tone } from "../../components/Badge";
import { Banner } from "../../components/Banner";
import { Button } from "../../components/Button";
import { NumberInput } from "../../components/Field";
import { Stat } from "../../components/Stat";
import { Table, type Column } from "../../components/Table";
import { count, dateTime, duration, of } from "../../format";
import { designLabel } from "../../labels";
import { useRefreshJob } from "./queries";
import { Stage } from "./Stage";
import styles from "./JobValidationPage.module.css";

type Plan = Schemas["TestPlanSummaryResponse"];

const POINTWISE_OFFSETS = 25; // per design, set by the backend's test-plan layout
const SECONDS_PER_GRASP = 20; // at the robot, roughly

export const PREDICTION: Record<Plan["prediction_status"], { tone: Tone; label: string }> = {
  pending: { tone: "neutral", label: "Prediction queued" },
  running: { tone: "active", label: "Predicting" },
  done: { tone: "ok", label: "Predicted" },
  failed: { tone: "bad", label: "Prediction failed" },
};

/** Stage 3: the trials to run at the robot. Each design gets the same point-wise offsets, repeated, plus random ones
 *  drawn from the experiment's camera-error model, so sim and robot are compared on exactly the same offsets. */
export function TestPlanStage({
  jobId,
  designs,
  plans,
  current,
  onChoose,
}: {
  jobId: string;
  designs: string[]; // what a new plan would test: the print selection plus IMP and STOCK
  plans: Plan[];
  current: Plan | undefined;
  onChoose: (planId: number) => void;
}) {
  const refresh = useRefreshJob(jobId);
  const [repeats, setRepeats] = useState<number | null>(3);
  const [random, setRandom] = useState<number | null>(30);
  const [seed, setSeed] = useState<number | null>(null);
  const [showForm, setShowForm] = useState(false);
  const create = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/jobs/{job_id}/test-plans", {
          params: { path: { job_id: jobId } },
          body: { pointwise_repeats: repeats ?? 3, random_per_design: random ?? 0, seed },
        }),
      ),
    onSuccess: (plan) => {
      setShowForm(false);
      onChoose(plan.id);
    },
    onSettled: refresh,
  });
  const valid = repeats != null && repeats >= 1 && random != null && random >= 0;
  const trials = valid ? designs.length * (POINTWISE_OFFSETS * repeats + random) : 0;
  const columns: Column<Plan>[] = [
    { key: "id", header: "Plan", render: (p) => `Plan ${p.id}` },
    { key: "created", header: "Created", sortValue: (p) => p.created, render: (p) => dateTime(p.created) },
    { key: "designs", header: "Designs", render: (p) => p.designs.map(designLabel).join(", ") },
    { key: "logged", header: "Logged", align: "right", render: (p) => of(p.logged, p.planned) },
    { key: "prediction", header: "Sim prediction", render: (p) => <Badge {...PREDICTION[p.prediction_status]} /> },
    {
      key: "use",
      header: "",
      align: "right",
      render: (p) =>
        p.id === current?.id ? (
          <span className={styles.note}>Showing below</span>
        ) : (
          <Button variant="ghost" size="sm" onClick={() => onChoose(p.id)}>
            Show this plan
          </Button>
        ),
    },
  ];

  return (
    <Stage
      step={3}
      title="Create a test plan"
      status={plans.length ? { tone: "ok", label: count(plans.length, "plan", "plans") } : { tone: "neutral", label: "No plan yet" }}
      description={`The sim and the robot get the same grasps: ${POINTWISE_OFFSETS} point-wise offsets, repeated, plus seeded random ones from the camera-error model.`}
    >
      {plans.length > 0 && (
        <Table label="Test plans" columns={columns} rows={plans} rowKey={(p) => String(p.id)} />
      )}
      {plans.length > 0 && !showForm ? (
        <div>
          <Button variant="secondary" onClick={() => setShowForm(true)}>
            Create another test plan
          </Button>
        </div>
      ) : (
        <div className={styles.panel}>
          <div className={styles.formRow}>
            <NumberInput
              label="Repeats of the point-wise offsets"
              value={repeats}
              onChange={setRepeats}
              min={1}
              step={1}
              hint="Default 3"
            />
            <NumberInput
              label="Random offsets per design"
              value={random}
              onChange={setRandom}
              min={0}
              step={1}
              hint="Default 30"
            />
            <NumberInput label="Seed" value={seed} onChange={setSeed} step={1} placeholder="Random" hint="Optional" />
          </div>
          <div className={styles.stats}>
            <Stat label="Designs tested" value={designs.length} detail={designs.map(designLabel).join(", ")} />
            <Stat label="Trials" value={trials} />
            <Stat label="Time at the robot" value={duration(trials * SECONDS_PER_GRASP)} detail="About 20 s per grasp" />
          </div>
          <div className={styles.actions}>
            <Button onClick={() => create.mutate()} disabled={!valid || create.isPending}>
              Create the test plan
            </Button>
            {plans.length > 0 && (
              <Button variant="secondary" onClick={() => setShowForm(false)}>
                Cancel
              </Button>
            )}
          </div>
          {create.error && <p className={styles.error}>{create.error.message}</p>}
        </div>
      )}
    </Stage>
  );
}

/** Stage 4: the sim predicts every trial in the plan, in a background worker on the GPU. */
export function PredictionStage({ jobId, plan }: { jobId: string; plan: Plan | undefined }) {
  const refresh = useRefreshJob(jobId);
  const compute = useCompute();
  const notReady = compute.data?.not_ready_reason;
  const again = useMutation({
    mutationFn: (planId: number) =>
      unwrap(
        api.POST("/api/jobs/{job_id}/test-plans/{plan_id}/predict", { params: { path: { job_id: jobId, plan_id: planId } } }),
      ),
    onSettled: refresh,
  });

  return (
    <Stage
      step={4}
      title="Wait for the sim's prediction"
      status={plan ? PREDICTION[plan.prediction_status] : { tone: "neutral", label: "Needs a test plan" }}
      description="Runs on the GPU in the background. You can leave this page."
    >
      {!plan && <p className={styles.note}>Create a test plan first.</p>}
      {plan?.prediction_status === "done" && (
        <p className={styles.note}>The sim has predicted all {plan.planned} trials in plan {plan.id}.</p>
      )}
      {(plan?.prediction_status === "pending" || plan?.prediction_status === "running") && (
        <p className={styles.note}>
          Predicting {plan.planned} trials.
        </p>
      )}
      {plan?.prediction_status === "failed" && (
        <Banner
          tone="bad"
          title="The prediction failed"
          action={
            <Button
              variant="secondary"
              size="sm"
              disabled={Boolean(notReady) || again.isPending}
              onClick={() => again.mutate(plan.id)}
            >
              Predict again
            </Button>
          }
        >
          {plan.prediction_error ?? "No reason given."}
        </Banner>
      )}
      {plan?.prediction_status === "failed" && notReady && (
        <p className={styles.note}>
          Predict again needs a ready GPU: {notReady} <Link to="/gpu">Connect a GPU</Link>
        </p>
      )}
      {again.error && <p className={styles.error}>{again.error.message}</p>}
    </Stage>
  );
}
