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
