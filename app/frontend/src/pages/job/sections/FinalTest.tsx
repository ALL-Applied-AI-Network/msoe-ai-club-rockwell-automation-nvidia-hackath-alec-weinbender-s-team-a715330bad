import { useMutation } from "@tanstack/react-query";
import { api, unwrap, type Schemas } from "../../../backend/client";
import { Card } from "../../../components/Card";
import { Checkbox } from "../../../components/Field";
import { Table, type Column } from "../../../components/Table";
import { degrees, mm, percent } from "../../../format";
import { designLabel, paramLabel } from "../../../labels";
import { useRefresh } from "../queries";
import type { Results } from "../types";
import styles from "../JobPage.module.css";

type FinalRow = Schemas["FinalRow"];

/** Every final design and the baselines, re-tested on the dense grid, with a "Print this" box per design
 *  (frontend-plan.md 7.1). Ticking saves the print selection the validation page starts from. */
export function FinalTest({ jobId, results }: { jobId: string; results: Results }) {
  const refresh = useRefresh(jobId);
  const save = useMutation({
    mutationFn: (designs: string[]) =>
      unwrap(api.PUT("/api/jobs/{job_id}/print-selection", { params: { path: { job_id: jobId } }, body: { designs } })),
    onSettled: refresh,
  });
  const rows = results.final_table;
  const printable = rows.filter((r) => r.kind === "search" || r.kind === "locked");
  const chosen = new Set(save.isPending && save.variables ? save.variables : printable.filter((r) => r.print_selected).map((r) => r.label));
  const metricLabel = results.summary?.task_metric_label;

  const columns: Column<FinalRow>[] = [
    { key: "label", header: "Design", render: (r) => <strong className={styles.design}>{designLabel(r.label)}</strong> },
    {
      key: "params",
      header: "Parameters",
      render: (r) => (r.params ? paramsText(r.params) : r.kind === "stock" ? "The cell's own fingers" : "A pad shaped to the part"),
    },
    { key: "success", header: "Success", align: "right", sortValue: (r) => r.success, render: (r) => percent(r.success) },
    {
      key: "capture",
      header: "Capture radius",
      align: "right",
      sortValue: (r) => r.capture_radius_mm,
      render: (r) => (r.capture_radius_mm == null ? "none" : mm(r.capture_radius_mm)),
    },
    ...(metricLabel
      ? [
          {
            key: "metric",
            header: "Task",
            align: "right" as const,
            sortValue: (r: FinalRow) => r.task_metric,
            render: (r: FinalRow) => (r.task_metric == null ? "none" : percent(r.task_metric)),
          },
        ]
      : []),
    {
      key: "print",
      header: "Print",
      render: (r) =>
        r.kind === "search" || r.kind === "locked" ? (
          <Checkbox
            label="Print this"
            checked={chosen.has(r.label)}
            disabled={save.isPending}
            onChange={(on) =>
              save.mutate(printable.map((p) => p.label).filter((l) => (l === r.label ? on : chosen.has(l))))
            }
          />
        ) : (
          <span className={styles.note}>Always tested</span>
        ),
    },
  ];

  return (
    <Card
      title="Final test"
      subtitle={`Re-tested on the dense grid at σ ${mm(results.header.error.sigma_mm)}.${
        metricLabel ? ` Task: the share of grasps ${metricLabel}.` : ""
      }`}
    >
      <Table label="Final test" columns={columns} rows={rows} rowKey={(r) => r.label} />
      {save.error && <p className={styles.error}>{save.error.message}</p>}
    </Card>
  );
}

function paramsText(params: Schemas["VPadParams"]): string {
  return Object.entries(params)
    .filter(([key]) => key !== "family")
    .map(([key, value]) => `${paramLabel(key)} ${key.endsWith("_deg") ? degrees(value as number) : mm(value as number)}`)
    .join(", ");
}
