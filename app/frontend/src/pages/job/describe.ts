import type { Schemas } from "../../backend/client";
import { degrees, mm, percent } from "../../format";
import { searchMethodLabel } from "../../labels";
import type { Results } from "./types";

// How an experiment's settings read in words on its page.

type Task = Schemas["Task"];
type ErrorModel = Schemas["ErrorModel"];
// The parts of /api/meta these read (the whole response doesn't fit its schema type: openapi-fetch widens tuples).
type Meta = { task_kinds: Schemas["TaskKindInfo"][]; error_presets: Schemas["ErrorPresetInfo"][] };

export type SimPath = { label: "Reference" | "CPU copies" | "GPU copies"; exploratory: boolean; detail: string };

/** Which way the Isaac sim server ran (frontend-plan.md rule 2), from the run's `sim` block: one environment on the CPU
 *  is the reference; copies on the CPU match it; copies on the GPU hold more grasps than the reference, so they're
 *  exploratory. Null for the mock sim, or when the server didn't say. */
export function simPath(sim: Record<string, unknown> | undefined): SimPath | null {
  if (!sim || sim.badge === "mock" || sim.backend === "mock") return null;
  const block = (typeof sim.describe === "object" && sim.describe !== null ? sim.describe : sim) as Record<string, unknown>;
  const envs = Number(block.envs ?? 1);
  const device = String(block.device ?? "cpu");
  if (!Number.isFinite(envs)) return null;
  const detail = `${envs} ${envs === 1 ? "environment" : "environments"} on ${device}`;
  if (envs <= 1) return { label: "Reference", exploratory: false, detail };
  if (device.startsWith("cuda")) return { label: "GPU copies", exploratory: true, detail };
  return { label: "CPU copies", exploratory: false, detail };
}

/** The task in a few words, e.g. "Pick and place, within 1.5 mm, normal transport". */
export function taskText(task: Task, meta: Meta | undefined): string {
  const kind = meta?.task_kinds.find((t) => t.name === task.kind)?.label ?? task.kind;
  const parts = [kind];
  if (task.offset_tolerance_mm != null) parts.push(`within ${mm(task.offset_tolerance_mm)}`);
  if (task.tilt_tolerance_deg != null) parts.push(`and ${degrees(task.tilt_tolerance_deg)}`);
  if (task.transport) parts.push(`${task.transport} transport`);
  return parts.join(", ");
}

/** The camera-error model in a few words, e.g. "σ 2.0 mm (range 0.5 to 5.0 mm), yaw 8°, bias 1.0 mm at 90°". */
export function errorText(error: ErrorModel): string {
  const parts = [`σ ${mm(error.sigma_mm)}`];
  if (error.sigma_range_mm) parts[0] += ` (range ${error.sigma_range_mm[0]} to ${mm(error.sigma_range_mm[1])})`;
  parts.push(`yaw ${degrees(error.sigma_deg)}`);
  if (error.bias_mm) parts.push(`bias ${mm(error.bias_mm)} at ${degrees(error.bias_direction_deg)}`);
  return parts.join(", ");
}

/** A job's resting poses with their shares of the score, from its scores: null for a job with one pose. */
export function scoredPoses(results: Results): Schemas["PoseScore"][] | null {
  return results.summary?.best.poses ?? results.final_table.find((row) => row.poses)?.poses ?? null;
}

/** The poses and their shares, e.g. "Lying on its side 62%, standing 38%". */
export function posesText(poses: { label?: string | null; weight: number }[]): string {
  const text = poses.map((p) => `${p.label ?? "unnamed pose"} ${percent(p.weight)}`).join(", ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Whether the run's camera error is one of the presets still waiting to be measured on the cell. */
export function isPlaceholderError(error: ErrorModel, meta: Meta | undefined): boolean {
  return meta?.error_presets.find((p) => p.name === error.preset)?.placeholder ?? false;
}

/** A search's method in words; the progress API sends it as a plain string. */
export const methodText = (method: string) =>
  ["bo", "sobol", "single"].includes(method) ? searchMethodLabel(method as "bo" | "sobol" | "single") : method;

const STOPS: Record<string, string> = {
  budget: "Used its whole budget",
  patience: "Stopped improving",
  single: "One design, evaluated",
  cancelled: "Cancelled",
};
export const stopText = (reason: string | null) => (reason ? (STOPS[reason] ?? reason) : "Still running");
