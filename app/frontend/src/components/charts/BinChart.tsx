import { Bar, BarChart, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { percent } from "../../format";
import { ChartFrame, ChartTooltip } from "./ChartFrame";
import { axisProps, useChartColors, type ChartColor } from "./chartColors";

export type Bin = {
  key: string;
  x: number; // the bin's centre or edge, in the x unit
  value: number; // 0 to 1: a share or a rate
  color?: ChartColor; // defaults to the chart's colour; e.g. bins past a tolerance in the warn tone
  details?: { label: string; value: string }[]; // more tooltip rows
};

type BinChartProps = {
  bins: Bin[];
  xLabel: string; // with its unit, e.g. "Offset in the hand (mm)"
  yLabel: string; // e.g. "Share of held grasps"
  formatX: (x: number) => string; // the bin's name in the tooltip, through format.ts
  color?: ChartColor;
  reference?: { x: number; label: string }; // e.g. the task's tolerance
  summary: string;
  note?: string;
};

/** A histogram or a rate per bin, one bar each: the in-hand offsets and tilts, misses by distance. One series, so no
 *  legend: the axis labels name it. */
export function BinChart({ bins, xLabel, yLabel, formatX, color = "acc", reference, summary, note }: BinChartProps) {
  const colors = useChartColors();
  const label = { fill: colors.faint, fontSize: 12 };
  const top = Math.max(0.05, ...bins.map((b) => b.value));
  return (
    <ChartFrame summary={summary} note={note}>
      <ResponsiveContainer width="100%" height={220}>
        <BarChart data={bins} margin={{ top: 16, right: 16, bottom: 28, left: 8 }} barCategoryGap={2}>
          <CartesianGrid vertical={false} stroke={colors.line} />
          <XAxis
            dataKey="x"
            tickFormatter={(v: number) => String(v)}
            label={{ value: xLabel, position: "insideBottom", offset: -16, ...label }}
            {...axisProps(colors)}
          />
          <YAxis
            type="number"
            domain={[0, Math.min(1, Math.ceil(top * 10) / 10)]}
            tickFormatter={(v: number) => percent(v)}
            width={48}
            label={{ value: yLabel, angle: -90, position: "insideLeft", offset: 8, ...label, style: { textAnchor: "middle" } }}
            {...axisProps(colors)}
          />
          {reference && (
            <ReferenceLine
              x={reference.x}
              stroke={colors.warn}
              strokeDasharray="4 4"
              label={{ value: reference.label, position: "insideTopRight", fill: colors.mute, fontSize: 12 }}
            />
          )}
          <Tooltip
            cursor={{ fill: colors["surface-2"] }}
            content={({ active, payload }) => {
              const bin = payload?.[0]?.payload as Bin | undefined;
              if (!active || !bin) return null;
              return <ChartTooltip title={formatX(bin.x)} rows={[{ label: yLabel.toLowerCase(), value: percent(bin.value) }, ...(bin.details ?? [])]} />;
            }}
          />
          <Bar dataKey="value" radius={[4, 4, 0, 0]} isAnimationActive={false} maxBarSize={36}>
            {bins.map((b) => (
              <Cell key={b.key} fill={colors[b.color ?? color]} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}
