import { useMemo } from "react";
import { useTheme } from "../../theme";

// The tokens charts draw with. Recharts sets fill and stroke as SVG attributes, which don't resolve var(--token), so a
// chart reads the tokens' values from tokens.css, again whenever the theme changes.
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

/** Every chart token's value, e.g. colors.acc is "#1d6b4f" in the light theme. */
export function useChartColors(): Record<ChartColor, string> {
  const theme = useTheme();
  return useMemo(() => {
    const style = getComputedStyle(document.documentElement);
    return Object.fromEntries(NAMES.map((name) => [name, style.getPropertyValue(`--${name}`).trim()])) as Record<
      ChartColor,
      string
    >;
  }, [theme]);
}

/** Axis, tick and grid props for every Recharts chart: hairline, recessive, text in the faint text token. */
export function axisProps(colors: Record<ChartColor, string>) {
  return {
    stroke: colors.line,
    tick: { fill: colors.faint, fontSize: 12 },
    tickLine: { stroke: colors.line },
  };
}
