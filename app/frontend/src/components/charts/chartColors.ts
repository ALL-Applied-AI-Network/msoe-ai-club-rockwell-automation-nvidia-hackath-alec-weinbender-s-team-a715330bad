import { useMemo } from "react";

// The tokens charts draw with. Recharts sets fill and stroke as SVG attributes, which don't resolve var(--token), so a
// chart reads the tokens' values once from tokens.css. The theme is dark only, so they never change while it's open.
const NAMES = [
  "acc",
  "ok",
  "bad",
  "warn",
  "active",
  "neutral",
  "ink",
  "mute",
  "faint",
  "line",
  "line-strong",
  "surface",
  "surface-2",
  "baseline",
  "search",
  "best",
] as const;

export type ChartColor = (typeof NAMES)[number];

/** Every chart token's value, e.g. colors.acc is "#76b900". */
export function useChartColors(): Record<ChartColor, string> {
  return useMemo(() => {
    const style = getComputedStyle(document.documentElement);
    return Object.fromEntries(NAMES.map((name) => [name, style.getPropertyValue(`--${name}`).trim()])) as Record<
      ChartColor,
      string
    >;
  }, []);
}

/** Axis, tick and grid props for every Recharts chart: hairline, recessive, text in the faint text token. */
export function axisProps(colors: Record<ChartColor, string>) {
  return {
    stroke: colors.line,
    tick: { fill: colors.faint, fontSize: 12 },
    tickLine: { stroke: colors.line },
  };
}
