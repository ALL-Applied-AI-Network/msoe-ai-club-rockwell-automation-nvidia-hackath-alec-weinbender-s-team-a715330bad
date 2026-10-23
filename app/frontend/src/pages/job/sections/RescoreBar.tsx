import { useEffect, useState } from "react";
import type { Schemas } from "../../../backend/client";
import { useMeta } from "../../../backend/queries";
import { Button } from "../../../components/Button";
import { Card } from "../../../components/Card";
import { Checkbox, NumberInput } from "../../../components/Field";
import { Select } from "../../../components/Select";
import type { Rescore } from "../queries";
import styles from "../JobPage.module.css";

type Task = Schemas["Task"];
type ErrorModel = Schemas["ErrorModel"];

type RescoreBarProps = {
  error: ErrorModel; // the run's own error model and task: where the bar starts, and what Reset returns to
  task: Task;
  active: boolean; // a re-scored view is showing
  pending: boolean;
  failure?: string;
  onChange: (request: Rescore | null) => void; // null: back to the run's own result
};

/** Re-scores the stored results at another camera error or task (frontend-plan.md 7.2). Nothing is simulated or stored:
 *  every grasp's raw outcome is kept, so any sigma, bias, task or tolerance scores again in a moment. Debounced. */
export function RescoreBar({ error: base, task: baseTask, active, pending, failure, onChange }: RescoreBarProps) {
  const meta = useMeta();
  const [error, setError] = useState(base);
  const [task, setTask] = useState(baseTask);
  const kinds = meta.data?.task_kinds ?? [];
  const tolerances = kinds.find((k) => k.name === task.kind)?.tolerances ?? [];

  useEffect(() => {
    const timer = setTimeout(() => {
      const same = JSON.stringify(error) === JSON.stringify(base) && JSON.stringify(task) === JSON.stringify(baseTask);
      const valid = error.sigma_mm > 0 && (!error.sigma_range_mm || error.sigma_range_mm[0] < error.sigma_range_mm[1]);
      if (valid) onChange(same ? null : { error: { ...error, preset: "custom" }, task });
    }, 400);
    return () => clearTimeout(timer);
  }, [error, task]); // only the user's edits re-score; the run's own values and onChange don't

  const reset = () => {
    setError(base);
    setTask(baseTask);
    onChange(null);
  };
  const setErr = (patch: Partial<ErrorModel>) => setError((e) => ({ ...e, ...patch }));

  return (
    <Card
      title="Re-score"
      subtitle="Score the stored grasps at another camera error or task. Nothing is simulated again."
      aside={
        <Button variant="secondary" size="sm" disabled={!active} onClick={reset}>
          Reset to the run
        </Button>
      }
    >
      <div className={styles.controls}>
        <NumberInput
          label="Camera error, sigma"
          unit="mm"
          min={0.1}
          step={0.1}
          value={error.sigma_mm}
          onChange={(v) => v != null && setErr({ sigma_mm: v })}
        />
        <NumberInput
          label="Yaw error, sigma"
          unit="°"
          min={0}
          step={1}
          value={error.sigma_deg}
          onChange={(v) => v != null && setErr({ sigma_deg: v })}
        />
        <NumberInput
          label="Bias"
          unit="mm"
          min={0}
          step={0.1}
          value={error.bias_mm}
          onChange={(v) => setErr({ bias_mm: v ?? 0 })}
        />
        <NumberInput
          label="Bias direction"
          unit="°"
          step={15}
          value={error.bias_direction_deg}
          onChange={(v) => setErr({ bias_direction_deg: v ?? 0 })}
        />
        <Select
          label="Task"
          value={task.kind}
          options={kinds.map((k) => ({ value: k.name, label: k.label }))}
          onChange={(event) => {
            const kind = event.target.value as Task["kind"];
            setTask((t) => ({
              ...t,
              kind,
              offset_tolerance_mm: kind === "drop" ? null : (t.offset_tolerance_mm ?? 1.5),
              tilt_tolerance_deg: kind === "insert" ? (t.tilt_tolerance_deg ?? 5) : null,
            }));
          }}
        />
        {tolerances.includes("offset_tolerance_mm") && (
          <NumberInput
            label="Offset tolerance"
            unit="mm"
            min={0}
            step={0.1}
            value={task.offset_tolerance_mm}
            onChange={(v) => setTask((t) => ({ ...t, offset_tolerance_mm: v }))}
          />
        )}
        {tolerances.includes("tilt_tolerance_deg") && (
          <NumberInput
            label="Tilt tolerance"
            unit="°"
            min={0}
            step={0.5}
            value={task.tilt_tolerance_deg}
            onChange={(v) => setTask((t) => ({ ...t, tilt_tolerance_deg: v }))}
          />
        )}
      </div>
      <Checkbox
        label="Design for a range of camera errors"
        checked={Boolean(error.sigma_range_mm)}
        onChange={(on) => setErr({ sigma_range_mm: on ? [Math.max(0.5, error.sigma_mm / 2), error.sigma_mm * 1.5] : null })}
      />
      {error.sigma_range_mm && (
        <div className={styles.controls}>
          <NumberInput
            label="From sigma"
            unit="mm"
            min={0.1}
            step={0.1}
            value={error.sigma_range_mm[0]}
            onChange={(v) => v != null && setErr({ sigma_range_mm: [v, error.sigma_range_mm![1]] })}
          />
          <NumberInput
            label="To sigma"
            unit="mm"
            min={0.1}
            step={0.1}
            value={error.sigma_range_mm[1]}
            onChange={(v) => v != null && setErr({ sigma_range_mm: [error.sigma_range_mm![0], v] })}
          />
        </div>
      )}
      {pending && <p className={styles.note}>Re-scoring</p>}
      {failure && <p className={styles.error}>{failure}</p>}
    </Card>
  );
}
