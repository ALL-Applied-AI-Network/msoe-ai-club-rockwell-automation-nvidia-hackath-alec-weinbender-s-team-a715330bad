import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { api, unwrapAs, type Schemas } from "../../backend/client";
import { meshUrl, useCellProfiles, useFingers, useParts } from "../../backend/queries";
import { Badge } from "../../components/Badge";
import { Banner } from "../../components/Banner";
import { Button, LinkButton } from "../../components/Button";
import { Card } from "../../components/Card";
import { KeyValues } from "../../components/KeyValues";
import { Notes } from "../../components/Notes";
import { Page } from "../../components/Page";
import { PartViewer } from "../../components/PartViewer";
import { Segmented } from "../../components/Segmented";
import { Select } from "../../components/Select";
import { EmptyState, Skeleton } from "../../components/States";
import { Table, type Column } from "../../components/Table";
import { dims, duration } from "../../format";
import { FINGER_FAMILIES, FINGER_SOURCES } from "../../labels";
import { errorText } from "../job/describe";
import styles from "./NewEvaluationPage.module.css";

type Part = Schemas["PartResponse"];
type Finger = Schemas["FingerResponse"];
type Spec = Schemas["EvaluationSpec"];
type Plan = Schemas["EvaluationPlanResponse"];
type Created = Schemas["CreateJobResponse"];

/** #/evaluate: a new evaluation job, or one per part for several: which parts, which cell, and which of its fingers (all
 *  of them by default). `?part=` starts with a part chosen; `?from=<job id>` starts from a copy of an evaluation. */
export function NewEvaluationPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const parts = useParts();
  const cells = useCellProfiles();
  const fingers = useFingers();
  const [chosen, setChosen] = useState<Set<string>>(() => new Set(params.get("part") ? [params.get("part")!] : []));
  const [cellId, setCellId] = useState<number | null>(null);
  const [which, setWhich] = useState<"all" | "some">("all");
  const [picked, setPicked] = useState<Set<string>>(new Set());

  // Starting from a copy: its part, cell and fingers.
  const from = params.get("from");
  const copy = useQuery({
    queryKey: ["duplicate", from],
    queryFn: () => unwrapAs<Spec>(api.POST("/api/jobs/{job_id}/duplicate", { params: { path: { job_id: from! } } })),
    enabled: Boolean(from),
    staleTime: Infinity,
  });
  useEffect(() => {
    if (!copy.data) return;
    setChosen(new Set([copy.data.part_id]));
    setCellId(copy.data.cell_profile_id);
    if (copy.data.finger_ids) {
      setWhich("some");
      setPicked(new Set(copy.data.finger_ids));
    }
  }, [copy.data]);

  const cell = cells.data?.find((c) => c.id === cellId) ?? cells.data?.[0];
  const forCell = (fingers.data ?? []).filter((f) => f.cell_profile_name === cell?.name && !f.archived);
  const partIds = [...chosen].filter((id) => parts.data?.some((p) => p.id === id)); // a stale ?part= is left out
  const spec: Spec | null =
    partIds.length > 0 && cell
      ? {
          kind: "evaluation",
          part_id: partIds[0],
          cell_profile_id: cell.id,
          poses: [],
          finger_ids: which === "all" ? null : [...picked],
          task: { kind: "drop" },
        }
      : null;
  const plan = useQuery({
    queryKey: ["evaluation-plan", spec],
    queryFn: () => unwrapAs<Plan>(api.POST("/api/jobs/plan", { body: spec! })),
    enabled: spec !== null,
    placeholderData: keepPreviousData,
  });
  const start = useMutation({
    mutationFn: async () => {
      if (partIds.length === 1) return [await unwrapAs<Created>(api.POST("/api/jobs", { body: spec! }))];
      return unwrapAs<Created[]>(api.POST("/api/jobs/batch", { body: { ...spec!, part_ids: partIds } }));
    },
    onSuccess: (made) => navigate(made.length === 1 ? `/jobs/${made[0].id}` : `/jobs?batch=${made[0].batch_id}`),
  });

  const review = (
    <Card title="Review" subtitle={partIds.length > 1 ? `For the first of ${partIds.length} parts; each runs as its own job` : undefined}>
      {!spec ? (
        <p className={styles.note}>Choose a part to see the plan.</p>
      ) : !plan.data ? (
        <Skeleton height={160} />
      ) : (
        <>
          <KeyValues
            items={[
              { label: "Fingers", value: String(plan.data.fingers.length) },
              { label: "Poses", value: String(plan.data.poses.length) },
              { label: "Grasps to simulate", value: plan.data.totals.total_grasps.toLocaleString() },
              {
                label: "Estimated time",
                value: plan.data.estimate.seconds != null ? duration(plan.data.estimate.seconds * partIds.length) : "Unknown until a run is measured",
              },
            ]}
          />
          {plan.data.blockers.length > 0 && (
            <Banner tone="bad" title="Can't start yet">
              <ul className={styles.list}>
                {plan.data.blockers.map((b) => (
                  <li key={b.reason}>{b.reason}</li>
                ))}
              </ul>
            </Banner>
          )}
          <Notes title="What this plan assumes" notes={plan.data.warnings} />
        </>
      )}
      {start.error && <p className={styles.error}>{start.error.message}</p>}
      <Button disabled={!spec || !plan.data || plan.data.blockers.length > 0 || start.isPending} onClick={() => start.mutate()}>
        {start.isPending ? "Starting" : partIds.length > 1 ? `Start ${partIds.length} evaluations` : "Start the evaluation"}
      </Button>
    </Card>
  );

  return (
    <Page title="New evaluation" description="Try the finger library on one part or several, and rank the fingers" rail={review} stretch={false}>
      <Card title="Parts" subtitle={`${partIds.length} chosen`} aside={<LinkButton variant="secondary" size="sm" to="/parts?upload=1">Upload parts</LinkButton>} flush>
        {parts.isPending ? (
          <Skeleton height={200} />
        ) : (parts.data ?? []).length === 0 ? (
          <EmptyState title="No parts yet">Upload a part's CAD first.</EmptyState>
        ) : (
          <PartTable
            parts={parts.data ?? []}
            chosen={chosen}
            onChoose={(id, on) =>
              setChosen((current) => {
                const next = new Set(current);
                if (on) next.add(id);
                else next.delete(id);
                return next;
              })
            }
          />
        )}
      </Card>

      <Card title="Cell">
        <div className={styles.row}>
          <Select
            label="Cell profile"
            value={String(cell?.id ?? "")}
            onChange={(event) => {
              setCellId(Number(event.target.value));
              setPicked(new Set());
            }}
            options={(cells.data ?? []).map((c) => ({ value: String(c.id), label: c.name }))}
          />
          {cell && (
            <KeyValues
              inline
              items={[
                { label: "Gripper", value: cell.profile.gripper_model },
                { label: "Grasp accuracy", value: errorText(cell.profile.grasp_accuracy) },
              ]}
            />
          )}
        </div>
      </Card>

      <Card
        title="Fingers"
        subtitle={which === "all" ? `All ${forCell.length} for this cell, its stock fingers included` : `${picked.size} chosen, plus the stock fingers`}
        aside={
          <Segmented
            label="Which fingers"
            value={which}
            onChange={setWhich}
            options={[
              { value: "all", label: "All of them" },
              { value: "some", label: "Choose" },
            ]}
          />
        }
        flush={which === "some"}
      >
        {which === "some" ? (
          <FingerTable
            fingers={forCell.filter((f) => f.source !== "stock")}
            picked={picked}
            onPick={(id, on) =>
              setPicked((current) => {
                const next = new Set(current);
                if (on) next.add(id);
                else next.delete(id);
                return next;
              })
            }
          />
        ) : (
          <div className={styles.chips}>
            {forCell.map((f) => (
              <Badge key={f.id} tone={f.source === "stock" ? "neutral" : "ok"} label={`${f.code} ${f.name}`} />
            ))}
          </div>
        )}
      </Card>
    </Page>
  );
}

function PartTable({ parts, chosen, onChoose }: { parts: Part[]; chosen: Set<string>; onChoose: (id: string, on: boolean) => void }) {
  const columns: Column<Part>[] = [
    {
      key: "part",
      header: "Part",
      width: "50%",
      render: (p) => (
        <div className={styles.part}>
          <PartViewer mode="icon" url={meshUrl(p.id)} label={p.name} />
          <div className={styles.lines}>
            <span className={styles.main}>{p.part_number ?? p.name}</span>
            <span className={styles.sub}>{p.part_number ? p.name : dims(p.extent_mm)}</span>
          </div>
        </div>
      ),
    },
    { key: "size", header: "Size", width: "30%", render: (p) => <span className={styles.sub}>{dims(p.extent_mm)}</span> },
    {
      key: "status",
      header: "Ready",
      width: "20%",
      render: (p) => (p.intake_status === "ready" ? <Badge tone="ok" label="Ready" /> : <Badge tone="warn" label="Needs a material" />),
    },
  ];
  return (
    <Table
      label="Parts"
      columns={columns}
      rows={parts}
      rowKey={(p) => p.id}
      selected={chosen}
      onSelect={onChoose}
      selectLabel="Evaluate"
      fixed
    />
  );
}

function FingerTable({ fingers, picked, onPick }: { fingers: Finger[]; picked: Set<string>; onPick: (id: string, on: boolean) => void }) {
  const columns: Column<Finger>[] = [
    {
      key: "finger",
      header: "Finger",
      width: "55%",
      render: (f) => (
        <div className={styles.lines}>
          <span className={styles.main}>{f.name}</span>
          <span className={styles.sub}>
            <code>{f.code}</code> {FINGER_SOURCES[f.source]}
          </span>
        </div>
      ),
    },
    { key: "family", header: "Family", width: "25%", render: (f) => FINGER_FAMILIES[f.family] ?? f.family },
    { key: "material", header: "Material", width: "20%", render: (f) => f.material },
  ];
  return (
    <Table
      label="Fingers to try"
      columns={columns}
      rows={fingers}
      rowKey={(f) => f.id}
      selected={picked}
      onSelect={onPick}
      selectLabel="Try"
      fixed
      empty="This cell has no fingers besides its stock ones yet."
    />
  );
}
