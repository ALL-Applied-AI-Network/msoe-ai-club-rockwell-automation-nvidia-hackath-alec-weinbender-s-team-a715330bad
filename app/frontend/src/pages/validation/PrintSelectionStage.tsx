import { useMutation } from "@tanstack/react-query";
import { api, unwrap, type Schemas } from "../../backend/client";
import { Table, type Column } from "../../components/Table";
import { mm, percent } from "../../format";
import { designLabel } from "../../labels";
import { useRefreshJob } from "./queries";
import { Stage } from "./Stage";
import styles from "./JobValidationPage.module.css";

type FinalRow = Schemas["FinalRow"];
type Selection = Schemas["PrintSelection"];

const COLUMNS: Column<FinalRow>[] = [
  { key: "label", header: "Design", render: (r) => <strong className={styles.design}>{designLabel(r.label)}</strong> },
  { key: "search", header: "Search", render: (r) => r.search || "Baseline" },
  {
    key: "success",
    header: "Predicted success",
    align: "right",
    sortValue: (r) => r.success,
    render: (r) => percent(r.success),
  },
  {
    key: "capture",
    header: "Capture radius",
    align: "right",
    sortValue: (r) => r.capture_radius_mm,
    render: (r) => (r.capture_radius_mm == null ? "none" : mm(r.capture_radius_mm)),
  },
];

/** Stage 1: which final designs to print. Stock and the imprint are always tested too, as the baselines. */
export function PrintSelectionStage({
  jobId,
  finalTable,
  selection,
}: {
  jobId: string;
  finalTable: FinalRow[];
  selection: Selection;
}) {
  const refresh = useRefreshJob(jobId);
  const save = useMutation({
    mutationFn: (designs: string[]) =>
      unwrap(api.PUT("/api/jobs/{job_id}/print-selection", { params: { path: { job_id: jobId } }, body: { designs } })),
    onSettled: refresh,
  });
  const rows = finalTable.filter((r) => r.kind === "search" || r.kind === "locked");
  const chosen = new Set(save.isPending && save.variables ? save.variables : selection.designs);
  const toggle = (label: string, on: boolean) => {
    const next = rows.map((r) => r.label).filter((l) => (l === label ? on : chosen.has(l)));
    save.mutate(next);
  };

  return (
    <Stage
      step={1}
      title="Choose the designs to print"
      status={chosen.size ? { tone: "ok", label: `${chosen.size} chosen` } : { tone: "neutral", label: "None chosen yet" }}
      description="Stock and the imprint are always tested too."
    >
      <Table
        label="Final designs"
        columns={COLUMNS}
        rows={rows}
        rowKey={(r) => r.label}
        selected={chosen}
        onSelect={toggle}
        selectLabel="Print"
      />
      {save.error && <p className={styles.error}>{save.error.message}</p>}
    </Stage>
  );
}
