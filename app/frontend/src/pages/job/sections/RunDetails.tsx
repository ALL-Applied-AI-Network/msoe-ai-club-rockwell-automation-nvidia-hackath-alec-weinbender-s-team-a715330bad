import { useState } from "react";
import type { Schemas } from "../../../backend/client";
import { useMeta } from "../../../backend/queries";
import { Banner } from "../../../components/Banner";
import { Button } from "../../../components/Button";
import { Card } from "../../../components/Card";
import { KeyValues } from "../../../components/KeyValues";
import { Table, type Column } from "../../../components/Table";
import { duration, of, percent } from "../../../format";
import { DownloadButton } from "../../../components/DownloadButton";
import { errorText, methodText, posesText, scoredPoses, simPath, stopText, taskText } from "../describe";
import type { Results } from "../types";
import styles from "../JobPage.module.css";

type Search = Schemas["SearchProgress"];

/** Everything needed to reproduce the run (frontend-plan.md 7.1), collapsed: each search's progress and why it stopped,
 *  the error model, the sim path, the GPU, versions and the seed, any warnings, and the raw data. */
export function RunDetails({ jobId, results }: { jobId: string; results: Results }) {
  const meta = useMeta();
  const [open, setOpen] = useState(false);
  const run = results.run;
  const path = simPath(run.sim);
  const poses = scoredPoses(results);
  const family = (name: string) => meta.data?.families.find((f) => f.name === name)?.label ?? name;
  const grid = (name: string) => {
    const g = run.grids[name] as { radii_mm?: number[]; n_directions?: number; yaws_deg?: number[] } | undefined;
    if (!g?.radii_mm) return "Not recorded";
    const points = (1 + g.radii_mm.length * (g.n_directions ?? 0)) * (g.yaws_deg?.length || 1);
    return `${points} offsets, out to ${Math.max(...g.radii_mm)} mm in ${g.n_directions} directions${
      (g.yaws_deg?.length ?? 1) > 1 ? `, ${g.yaws_deg!.length} yaw layers` : ""
    }`;
  };

  const columns: Column<Search>[] = [
    { key: "family", header: "Family", render: (s) => family(s.family) },
    { key: "method", header: "Method", render: (s) => methodText(s.method) },
    { key: "designs", header: "Designs", align: "right", render: (s) => of(s.designs_evaluated, s.budget) },
    { key: "initial", header: "Starting designs", align: "right", render: (s) => String(s.n_initial) },
    { key: "batch", header: "Batch size", align: "right", render: (s) => String(s.batch_size) },
    { key: "rounds", header: "Rounds", align: "right", render: (s) => String(s.rounds) },
    { key: "best", header: "Best", align: "right", render: (s) => (s.best == null ? "none" : percent(s.best)) },
    { key: "stop", header: "Stopped", render: (s) => stopText(s.stop_reason) },
  ];

  return (
    <Card
      title="Run details"
      aside={
        <Button variant="ghost" size="sm" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
          {open ? "Hide" : "Show"}
        </Button>
      }
    >
      {run.warnings.length > 0 && (
        <Banner tone="warn" title={run.warnings.length === 1 ? "A warning from the run" : `${run.warnings.length} warnings from the run`}>
          <ul className={styles.list}>
            {run.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </Banner>
      )}
      {open && (
        <>
          <Table label="Searches" columns={columns} rows={run.searches} rowKey={(s) => s.key} />
          <KeyValues
            items={[
              { label: "Rounds", value: of(run.rounds, run.n_rounds) },
              { label: "Run time", value: run.runtime_s == null ? "Not finished" : duration(run.runtime_s) },
              { label: "Camera error", value: errorText(run.error) },
              { label: "Task", value: taskText(run.task, meta.data) },
              ...(poses ? [{ label: "Resting poses", value: posesText(poses) }] : []),
              { label: "Search grid", value: grid("search") },
              { label: "Final grid", value: grid("final") },
              { label: "Sim", value: path ? `${path.label}: ${path.detail}` : String(run.sim.backend ?? "mock") },
              { label: "GPU", value: run.gpu ?? "None recorded" },
              { label: "Seed", value: String(run.seed), mono: true },
              ...Object.entries(run.versions).map(([name, version]) => ({ label: name, value: version ?? "unknown", mono: true })),
            ]}
          />
          <div className={styles.row}>
            <DownloadButton href={`/api/jobs/${encodeURIComponent(jobId)}/run-metadata.json`} label="Run metadata (.json)" />
            <DownloadButton href={`/api/export/trials.jsonl?job_id=${encodeURIComponent(jobId)}`} label="Every simulated design (.jsonl)" />
          </div>
        </>
      )}
    </Card>
  );
}
