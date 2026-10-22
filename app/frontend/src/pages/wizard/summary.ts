import type { Schemas } from "../../backend/client";
import type { useMeta } from "../../backend/queries";
import { degrees, duration, mm } from "../../format";

/** `/api/meta` as useMeta() returns it. */
export type Meta = NonNullable<ReturnType<typeof useMeta>["data"]>;

// The wizard's choices in words, for the summary rail and the review step.

/** "Pick and place, within 1.5 mm, with a fast transport move". */
export function taskLabel(task: Schemas["Task"], meta: Meta): string {
  const parts = [meta.task_kinds.find((k) => k.name === task.kind)?.label ?? task.kind];
  if (task.offset_tolerance_mm != null && task.kind !== "drop") parts.push(`within ${mm(task.offset_tolerance_mm)}`);
  if (task.tilt_tolerance_deg != null && task.kind === "insert") parts.push(`tilted at most ${degrees(task.tilt_tolerance_deg)}`);
  if (task.transport) {
    const transport = meta.transports.find((t) => t.name === task.transport);
    parts.push(`with a ${transport?.label.toLowerCase() ?? task.transport} transport move`);
  }
  return parts.join(", ");
}

/** The plan's run-time estimate: "About 40 min", "Under a second" (the mock sim), or "Unknown" while no runs on this sim
 *  have measured it. */
export function estimateText(seconds: number | null): string {
  if (seconds == null) return "Unknown";
  if (seconds < 1) return "Under a second";
  return `About ${duration(seconds)}`;
}

/** "Typical, sigma 3.0 mm and 8°", or a range: "Custom, sigma 1.0 to 4.0 mm". */
export function errorLabel(error: Schemas["ErrorModel"], meta: Meta): string {
  const preset = meta.error_presets.find((p) => p.name === error.preset)?.label ?? "Custom";
  const sigma = error.sigma_range_mm
    ? `sigma ${error.sigma_range_mm[0].toFixed(1)} to ${mm(error.sigma_range_mm[1])}`
    : `sigma ${mm(error.sigma_mm)}`;
  const bias = error.bias_mm > 0 ? `, bias ${mm(error.bias_mm)} at ${degrees(error.bias_direction_deg)}` : "";
  return `${preset}, ${sigma} and ${degrees(error.sigma_deg)}${bias}`;
}
