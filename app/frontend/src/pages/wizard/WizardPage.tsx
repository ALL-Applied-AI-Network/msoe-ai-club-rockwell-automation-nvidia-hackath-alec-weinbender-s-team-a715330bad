import { useQuery } from "@tanstack/react-query";
import { useEffect, useState, type ComponentType } from "react";
import { Navigate, useLocation, useNavigate, useParams, useSearchParams } from "react-router";
import { api, unwrapAs, type Schemas } from "../../backend/client";
import { useMeta } from "../../backend/queries";
import { Banner } from "../../components/Banner";
import { Button, LinkButton } from "../../components/Button";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Page } from "../../components/Page";
import { ErrorState, Skeleton } from "../../components/States";
import { StepLayout, type StepItem, type StepStatus } from "../../components/StepLayout";
import { WIZARD_STEPS } from "../../labels";
import { DraftProvider, useDraft, type Draft } from "./draft";
import { CellStep } from "./steps/CellStep";
import { ErrorStep } from "./steps/ErrorStep";
import { FamiliesStep } from "./steps/FamiliesStep";
import { GraspStep } from "./steps/GraspStep";
import { PartStep } from "./steps/PartStep";
import { PoseStep } from "./steps/PoseStep";
import { ReviewStep } from "./steps/ReviewStep";
import { TaskStep } from "./steps/TaskStep";
import { SummaryRail } from "./SummaryRail";
import type { Meta } from "./summary";
import styles from "./Wizard.module.css";

// A line under the title only where the title alone doesn't say what the step decides. The steps hold the rest.
const STEPS: { Component: ComponentType; description?: string }[] = [
  { Component: PartStep },
  { Component: PoseStep },
  { Component: TaskStep },
  { Component: CellStep },
  { Component: GraspStep, description: "Which way the jaws close on the part." },
  { Component: FamiliesStep, description: "Which finger shapes are searched, and over which ranges." },
  { Component: ErrorStep, description: "How far off the camera can be." },
  { Component: ReviewStep },
];

/** #/new/:step: the new-experiment wizard (docs/notes/frontend-plan.md, section 5). `?from=<job id>` starts from a copy
 *  of that experiment's inputs, at the step in the address; `?part=<id>` starts a new draft with that part, at step 2. */
export function WizardPage() {
  return (
    <DraftProvider>
      <Wizard />
    </DraftProvider>
  );
}

function Wizard() {
  const { step } = useParams();
  const index = WIZARD_STEPS.findIndex((s) => s.slug === step);
  const starting = useDraftStart();
  const [confirmReset, setConfirmReset] = useState(false);
  const { draft, reset } = useDraft();
  const navigate = useNavigate();

  if (index < 0) return <Navigate to="/new/part" replace />;

  const startOver = (
    <Button variant="secondary" onClick={() => setConfirmReset(true)} disabled={Object.keys(draft).length === 0}>
      Start over
    </Button>
  );

  return (
    <Page title="New experiment" description={draft.name || undefined} actions={startOver}>
      {starting.error ? (
        <ErrorState title="Couldn't copy the experiment" message={starting.error.message} />
      ) : starting.loading ? (
        <Skeleton height={480} />
      ) : (
        <WizardStep index={index} />
      )}
      <ConfirmDialog
        open={confirmReset}
        title="Start over?"
        confirmLabel="Clear the wizard"
        cancelLabel="Keep my choices"
        danger
        onConfirm={() => {
          reset({});
          setConfirmReset(false);
          navigate("/new/part");
        }}
        onClose={() => setConfirmReset(false)}
      >
        This clears every choice in the wizard. Uploaded parts and saved cell profiles are kept.
      </ConfirmDialog>
    </Page>
  );
}

function WizardStep({ index }: { index: number }) {
  const { draft, gates, plan } = useDraft();
  const navigate = useNavigate();
  const location = useLocation();
  const runError = (location.state as { runError?: string } | null)?.runError; // Run was refused for this step
  const { Component, description } = STEPS[index];
  const blockers = plan.data?.blockers ?? [];
  useEffect(() => {
    window.scrollTo(0, 0); // each step opens at its top (in braces: Chromium's scrollTo returns a promise)
  }, [index]);

  // Whether each step's inputs are filled in, for steps the user hasn't opened in this visit (a copied experiment).
  // Steps with defaults (task, families, camera error) count once the user is past them, or when copied.
  const copied = Boolean(draft.duplicated_from);
  const past = (n: number) => copied || index >= n; // index is 0-based, so index >= n means step n is behind
  const filled: Record<number, boolean> = {
    1: Boolean(draft.part_id),
    2: (draft.poses?.length ?? 0) > 0,
    3: past(3) && Boolean(draft.task),
    4: draft.cell_profile_id != null,
    5: (draft.poses?.length ?? 0) > 0 && draft.poses!.every((p) => p.grasp),
    6: past(6),
    7: past(7) && Boolean(draft.error),
  };

  const steps: StepItem[] = WIZARD_STEPS.map((s, i) => {
    const n = i + 1;
    const blocker = blockers.find((b) => b.step === n);
    const gate = gates[n];
    let status: StepStatus = gate ? (gate.ok ? "done" : "attention") : filled[n] ? "done" : "todo";
    if (blocker) status = "blocked";
    else if (i === index) status = "current";
    return { key: s.slug, label: s.label, to: `/new/${s.slug}`, status, note: blocker?.reason ?? (gate?.ok ? undefined : gate?.reason) };
  });

  const gate = gates[index + 1];
  const canGoOn = gate?.ok ?? true;
  const previous = WIZARD_STEPS[index - 1];
  const next = WIZARD_STEPS[index + 1];

  return (
    <StepLayout
      steps={steps}
      current={index}
      title={WIZARD_STEPS[index].label}
      description={description}
      rail={<SummaryRail />}
      footer={
        <>
          {previous && (
            <LinkButton variant="secondary" to={`/new/${previous.slug}`}>
              Back to {previous.label.toLowerCase()}
            </LinkButton>
          )}
          {next && (
            <div className={styles.next}>
              {!canGoOn && gate?.reason && <span className={styles.reason}>{gate.reason}</span>}
              <Button disabled={!canGoOn} onClick={() => navigate(`/new/${next.slug}`)}>
                Next: {next.label.toLowerCase()}
              </Button>
            </div>
          )}
        </>
      }
    >
      {runError && (
        <Banner tone="bad" title="Run was refused">
          {runError}
        </Banner>
      )}
      <Component />
    </StepLayout>
  );
}

/** Starts the draft from the address: a copy of an experiment (`?from=`), a part from the library (`?part=`), or the
 *  stored draft. Fills in the defaults a new draft needs (a seed, the task, the camera error) so the plan can run as soon
 *  as there's a grasp. The query parameters are dropped once used, so moving between steps doesn't start again. */
function useDraftStart(): { loading: boolean; error: Error | null } {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const { draft, reset, update } = useDraft();
  const meta = useMeta();
  const from = params.get("from");
  const partId = params.get("part");

  const copy = useQuery({
    queryKey: ["duplicate", from],
    queryFn: () => unwrapAs<Schemas["JobSpec"]>(api.POST("/api/jobs/{job_id}/duplicate", { params: { path: { job_id: from! } } })),
    enabled: from !== null,
    staleTime: Infinity,
    gcTime: 0,
  });

  useEffect(() => {
    if (from && copy.data) {
      reset({ ...copy.data, duplicated_from: from });
      setParams({}, { replace: true });
    }
  }, [from, copy.data, reset, setParams]);

  useEffect(() => {
    if (partId) {
      reset({ part_id: partId });
      navigate("/new/pose", { replace: true });
    }
  }, [partId, reset, navigate]);

  useEffect(() => {
    if (!meta.data || from || partId) return;
    const missing: Draft = {};
    if (draft.seed == null) missing.seed = Math.floor(Math.random() * 1_000_000);
    if (!draft.task) missing.task = { kind: "drop" };
    if (!draft.error) missing.error = defaultError(meta.data);
    if (Object.keys(missing).length > 0) update(missing);
  }, [meta.data, from, partId, draft.seed, draft.task, draft.error, update]);

  return { loading: from !== null && copy.isPending, error: copy.error };
}

/** The camera-error preset the backend calls its default, as an error model. */
function defaultError(meta: Meta): Schemas["ErrorModel"] {
  const preset = meta.error_presets.find((p) => p.note.includes("default")) ?? meta.error_presets.find((p) => p.name === "typical");
  return {
    preset: (preset?.name ?? "typical") as Schemas["ErrorModel"]["preset"],
    sigma_mm: preset?.sigma_mm ?? 3,
    sigma_deg: preset?.sigma_deg ?? 8,
    sigma_range_mm: null,
    bias_mm: 0,
    bias_direction_deg: 0,
  };
}
