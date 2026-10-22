import { CartesianGrid, ErrorBar, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from "recharts";
import { percent } from "../../format";
import { ChartFrame, ChartTooltip, type LegendItem } from "./ChartFrame";
import { axisProps, useChartColors } from "./chartColors";
import { Mark } from "./MarkShape";

export type IntervalRow = {
  key: string;
  label: string; // the row's name on the axis, e.g. "D1", "Stock"
  predicted: number | null; // 0 to 1
  measured: number | null; // 0 to 1
  low: number | null; // the measured rate's 95% interval
  high: number | null;
  n?: number; // trials behind the measured rate
};

type IntervalChartProps = {
  rows: IntervalRow[];
  summary: string; // the text alternative
  note?: string;
};

const LEGEND: LegendItem[] = [
  { label: "Predicted by the sim", color: "mute", shape: "ring" },
  { label: "Measured on the robot", description: "with its 95% interval", color: "acc", shape: "dot" },
];

/** Predicted against measured success, one row per design: the sim's prediction as a ring, the robot's measured rate
 *  as a dot with its 95% interval. Where the ring sits outside the bar, the sim missed. */
export function IntervalChart({ rows, summary, note }: IntervalChartProps) {
  const colors = useChartColors();
  const predicted = rows.filter((r) => r.predicted != null).map((r) => ({ ...r, x: r.predicted }));
  const measured = rows
    .filter((r) => r.measured != null)
    .map((r) => ({ ...r, x: r.measured, error: [r.measured! - (r.low ?? r.measured!), (r.high ?? r.measured!) - r.measured!] }));

  return (
    <ChartFrame summary={summary} legend={LEGEND} note={note}>
      <ResponsiveContainer width="100%" height={rows.length * 44 + 56}>
        <ScatterChart margin={{ top: 8, right: 24, bottom: 24, left: 8 }}>
          <CartesianGrid horizontal={false} stroke={colors.line} />
          <XAxis
            type="number"
            dataKey="x"
            domain={[0, 1]}
            ticks={[0, 0.25, 0.5, 0.75, 1]}
            tickFormatter={(v: number) => percent(v)}
            label={{ value: "Success rate", position: "insideBottom", offset: -16, fill: colors.faint, fontSize: 12 }}
            {...axisProps(colors)}
          />
          <YAxis type="category" dataKey="label" width={72} allowDuplicatedCategory={false} {...axisProps(colors)} />
          <Tooltip
            cursor={false}
            content={({ active, payload }) => {
              const row = payload?.[0]?.payload as IntervalRow | undefined;
              if (!active || !row) return null;
              return (
                <ChartTooltip
                  title={row.label}
                  rows={[
                    { label: "predicted", value: row.predicted == null ? "none" : percent(row.predicted) },
                    { label: "measured", value: row.measured == null ? "none yet" : percent(row.measured) },
                    ...(row.low != null && row.high != null
                      ? [{ label: "95% interval", value: `${percent(row.low)} to ${percent(row.high)}` }]
                      : []),
                    ...(row.n != null ? [{ label: "trials", value: row.n }] : []),
                  ]}
                />
              );
            }}
          />
          <Scatter
            data={measured}
            isAnimationActive={false}
            shape={(props: { cx?: number; cy?: number }) => (
              <g>
                <circle cx={props.cx} cy={props.cy} r={12} fill="transparent" />
                <Mark shape="dot" cx={props.cx ?? 0} cy={props.cy ?? 0} color={colors.acc} ring={colors.surface} />
              </g>
            )}
          >
            <ErrorBar dataKey="error" direction="x" width={8} strokeWidth={2} stroke={colors.acc} />
          </Scatter>
          <Scatter
            data={predicted}
            isAnimationActive={false}
            shape={(props: { cx?: number; cy?: number }) => (
              <g>
                <circle cx={props.cx} cy={props.cy} r={12} fill="transparent" />
                <Mark shape="ring" cx={props.cx ?? 0} cy={props.cy ?? 0} size={6} color={colors.mute} ring={colors.surface} />
              </g>
            )}
          />
        </ScatterChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}
