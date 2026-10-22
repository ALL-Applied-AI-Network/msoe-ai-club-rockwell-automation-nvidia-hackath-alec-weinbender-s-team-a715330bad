import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { percent } from "../../format";
import { ChartFrame, ChartTooltip, type LegendItem } from "./ChartFrame";
import { axisProps, useChartColors, type ChartColor } from "./chartColors";

export type SearchLine = {
  key: string; // the search's key, e.g. "vpad"
  label: string; // e.g. "V-pad"
  bestSoFar: number[]; // the best success after each design evaluated, 0 to 1
  initial: number; // how many starting designs round 0 had
};

// Fixed order, never cycled: a job has one search per finger family, and only a few families exist.
const ORDER: ChartColor[] = ["acc", "active", "ink"];

type SearchProgressChartProps = {
  searches: SearchLine[];
  summary: string;
  note?: string;
};

/** Best success so far against designs evaluated, one line per search: how the search is converging. Round 0's
 *  starting designs are marked, so it's clear where the Bayesian search took over. */
export function SearchProgressChart({ searches, summary, note }: SearchProgressChartProps) {
  const colors = useChartColors();
  const length = Math.max(0, ...searches.map((s) => s.bestSoFar.length));
  const rows = Array.from({ length }, (_, i) => ({
    designs: i + 1,
    ...Object.fromEntries(searches.map((s) => [s.key, s.bestSoFar[i] ?? null])),
  }));
  const legend: LegendItem[] | undefined =
    searches.length > 1 ? searches.map((s, i) => ({ label: s.label, color: ORDER[i % ORDER.length], shape: "dot" })) : undefined;
  const initial = searches[0]?.initial ?? 0;
  const label = { fill: colors.faint, fontSize: 12 };

  return (
    <ChartFrame summary={summary} legend={legend} note={note}>
      <ResponsiveContainer width="100%" height={260}>
        <LineChart data={rows} margin={{ top: 12, right: 24, bottom: 28, left: 8 }}>
          <CartesianGrid vertical={false} stroke={colors.line} />
          {initial > 0 && initial < length && (
            <ReferenceLine
              x={initial}
              stroke={colors["line-strong"]}
              strokeDasharray="4 4"
              label={{ value: "Starting designs end", position: "insideTopLeft", ...label }}
            />
          )}
          <XAxis
            type="number"
            dataKey="designs"
            domain={[1, Math.max(2, length)]}
            allowDecimals={false}
            label={{ value: "Designs evaluated", position: "insideBottom", offset: -16, ...label }}
            {...axisProps(colors)}
          />
          <YAxis
            type="number"
            domain={[0, 1]}
            ticks={[0, 0.25, 0.5, 0.75, 1]}
            tickFormatter={(v: number) => percent(v)}
            width={48}
            {...axisProps(colors)}
          />
          <Tooltip
            cursor={{ stroke: colors["line-strong"] }}
            content={({ active, payload, label: designs }) => {
              if (!active || !payload?.length) return null;
              return (
                <ChartTooltip
                  title={`After ${designs} designs`}
                  rows={payload
                    .filter((p) => p.value != null)
                    .map((p) => ({ label: `best, ${p.name ?? ""}`, value: percent(Number(p.value)) }))}
                />
              );
            }}
          />
          {searches.map((s, i) => (
            <Line
              key={s.key}
              type="stepAfter"
              dataKey={s.key}
              name={s.label}
              stroke={colors[ORDER[i % ORDER.length]]}
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
              connectNulls
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}
