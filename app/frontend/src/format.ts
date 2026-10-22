// The one place numbers become text (.claude/rules/coding-style.md, "Frontend"): every page shows them the same way.

/** A count of things, e.g. "no GPU processes", "1 GPU process", "3 GPU processes". */
export function count(n: number, one: string, many: string): string {
  return n === 0 ? `no ${many}` : `${n} ${n === 1 ? one : many}`;
}

/** A count of minutes, e.g. "20 min", "2.5 min". */
export function minutes(value: number): string {
  return `${Number.isInteger(value) ? value : value.toFixed(1)} min`;
}

/** A time span in seconds, e.g. "45 s", "12 min", "1 h 05 min". */
export function duration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)} s`;
  const total = Math.round(seconds / 60);
  if (total < 60) return `${total} min`;
  return `${Math.floor(total / 60)} h ${String(total % 60).padStart(2, "0")} min`;
}

/** A Unix time (seconds) as the viewer's clock time, e.g. "14:05". */
export function clockTime(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

/** A Unix time (seconds) relative to now: "just now", "5 min ago", "3 h ago", then the date, e.g. "Oct 20, 14:05". */
export function timeAgo(epochSeconds: number, now = Date.now() / 1000): string {
  const ago = now - epochSeconds;
  if (ago < 60) return "just now";
  if (ago < 3600) return `${Math.floor(ago / 60)} min ago`;
  if (ago < 86400) return `${Math.floor(ago / 3600)} h ago`;
  const date = new Date(epochSeconds * 1000);
  return `${date.toLocaleDateString([], { month: "short", day: "numeric" })}, ${clockTime(epochSeconds)}`;
}

/** A success rate (0 to 1) as a whole percentage, e.g. "92%". Above 99.5% it shows one decimal, rounded down, so a
 *  near miss reads "99.9%" and never as a perfect "100%". */
export function percent(fraction: number): string {
  const value = fraction * 100;
  if (value > 99.5 && value < 100) return `${(Math.floor(value * 10) / 10).toFixed(1)}%`;
  return `${Math.round(value)}%`;
}

/** A length in mm, e.g. "5.0 mm". */
export function mm(value: number, digits = 1): string {
  return `${value.toFixed(digits)} mm`;
}

/** "3 of 9": progress through a count. */
export function of(done: number, total: number): string {
  return `${done} of ${total}`;
}

/** A bounding box or other dimensions in mm, e.g. "31.8 × 31.8 × 15.7 mm". */
export function dims(values: readonly number[], digits = 1): string {
  return `${values.map((v) => v.toFixed(digits)).join(" × ")} mm`;
}

/** An angle in degrees, e.g. "8°". */
export function degrees(value: number, digits = 0): string {
  return `${value.toFixed(digits)}°`;
}

/** A force in newtons, e.g. "2.5 N". */
export function newtons(value: number): string {
  return `${trim(value)} N`;
}

const GRAMS_PER: Record<"g" | "kg" | "oz" | "lb", number> = { g: 1, kg: 1000, oz: 28.349523125, lb: 453.59237 };

/** A mass given in grams, shown in the user's unit, e.g. "5.2 g", "0.18 oz". */
export function mass(grams: number, unit: "g" | "kg" | "oz" | "lb" = "g"): string {
  const value = grams / GRAMS_PER[unit];
  return `${value >= 100 ? value.toFixed(0) : value >= 10 ? value.toFixed(1) : value.toPrecision(2)} ${unit}`;
}

/** Grams from a mass typed in the user's unit. */
export function toGrams(value: number, unit: "g" | "kg" | "oz" | "lb"): number {
  return value * GRAMS_PER[unit];
}

/** A Unix time (seconds) as a date and time, e.g. "Oct 20, 2026, 14:05". */
export function dateTime(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

/** A number without trailing zeros: 2.5, 40, 0.35. */
export function trim(value: number, digits = 2): string {
  return String(Number(value.toFixed(digits)));
}

/** A difference between two success rates (0 to 1) in percentage points, signed, e.g. "+67 points", "-3 points". */
export function points(delta: number): string {
  const value = Math.round(delta * 100);
  return `${value > 0 ? "+" : ""}${value} ${Math.abs(value) === 1 ? "point" : "points"}`;
}

/** A number with any unit, without trailing zeros, e.g. "0.6 MPa", "0.017 s", "1920 px". */
export function quantity(value: number, unit: string, digits = 3): string {
  return `${trim(value, digits)} ${unit}`;
}

/** A finger parameter's value in its unit from the API ("mm" or "deg"), e.g. "2.4 mm", "120°". */
export function paramValue(value: number, unit: string): string {
  if (unit === "deg") return degrees(value);
  if (unit === "mm") return mm(value);
  return quantity(value, unit);
}

/** A grasp's offset from where the camera put the part: "x 4.0 mm, y -2.0 mm", plus the yaw when it isn't 0. */
export function offset(dx: number, dy: number, yawDeg = 0): string {
  const xy = `x ${mm(dx)}, y ${mm(dy)}`;
  return Math.abs(yawDeg) < 1e-9 ? xy : `${xy}, yaw ${degrees(yawDeg)}`;
}
