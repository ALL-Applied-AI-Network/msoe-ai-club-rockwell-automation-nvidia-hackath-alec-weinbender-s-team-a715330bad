import {
  CartesianGrid,
  ComposedChart,
  ErrorBar,
  Line,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { mm, percent } from "../../format";
import { ChartFrame, ChartTooltip, type LegendItem } from "./ChartFrame";
import { axisProps, useChartColors, type ChartColor } from "./chartColors";
import { Mark, type MarkShapeName } from "./MarkShape";

export type CurveSeries = {
  key: string; // e.g. "D1", "STOCK"
  label: string; // e.g. "D1", "Stock"
  points: { sigma: number; success: number }[]; // success 0 to 1 at each sigma in mm
  color: ChartColor;
  shape: MarkShapeName;
  emphasis?: boolean; // the leading design: a heavier line
  dashed?: boolean; // the baselines
};

export type MeasuredPoint = {
  key: string;
  label: string; // the design it measures, e.g. "D1"
  sigma: number;
  success: number;
  low: number; // the 95% interval
  high: number;
  n: number; // trials
};

type SuccessCurveChartProps = {
  series: CurveSeries[];
  measured?: MeasuredPoint[]; // physical trials, with their 95% intervals
  target: number; // the target sigma, mm
  targetRange?: readonly [number, number] | null; // "design for a range" of sigmas
  summary: string;
  note?: string;
};

/** Predicted success against camera error (sigma, mm), one line per design: the core claim of a result. The target
 *  sigma is marked, and measured points from the robot sit on top with their 95% intervals, where prediction meets
 *  reality. */
export function SuccessCurveChart({ series, measured = [], target, targetRange, summary, note }: SuccessCurveChartProps) {
  const colors = useChartColors();
  const sigmas = [...new Set(series.flatMap((s) => s.points.map((p) => p.sigma)))].sort((a, b) => a - b);
  const rows = sigmas.map((sigma) => ({
    sigma,
    ...Object.fromEntries(series.map((s) => [s.key, s.points.find((p) => p.sigma === sigma)?.success ?? null])),
  }));
  const measuredData = measured.map((m) => ({ ...m, x: m.sigma, y: m.success, error: [m.success - m.low, m.high - m.success] }));
  const legend: LegendItem[] = [
    ...series.map(({ label, color, shape }) => ({ label, color, shape })),
    ...(measured.length ? [{ label: "Measured on the robot", description: "with its 95% interval", color: "ink" as const, shape: "triangle" as const }] : []),
  ];
  const label = { fill: colors.faint, fontSize: 12 };

  return (
    <ChartFrame summary={summary} legend={legend} note={note}>
      <ResponsiveContainer width="100%" height={320}>
        <ComposedChart data={rows} margin={{ top: 12, right: 24, bottom: 28, left: 8 }}>
          <CartesianGrid vertical={false} stroke={colors.line} />
          {targetRange && (
            <ReferenceArea x1={targetRange[0]} x2={targetRange[1]} fill={colors.acc} fillOpacity={0.06} stroke="none" />
          )}
          <ReferenceLine
            x={target}
            stroke={colors["line-strong"]}
            strokeDasharray="4 4"
            label={{ value: `Target ${mm(target)}`, position: "insideTopRight", ...label }}
          />
          <XAxis
            type="number"
            dataKey="sigma"
            domain={[0, Math.max(5, ...sigmas)]}
            tickFormatter={(v: number) => String(v)}
            label={{ value: "Camera error, sigma (mm)", position: "insideBottom", offset: -16, ...label }}
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
            content={({ active, payload, label: sigma }) => {
              if (!active || !payload?.length) return null;
              const row = rows.find((r) => r.sigma === sigma) as Record<string, number | null> | undefined;
              if (!row) return null;
              return (
                <ChartTooltip
                  title={`At sigma ${mm(Number(sigma))}`}
                  rows={series
                    .filter((s) => row[s.key] != null)
                    .map((s) => ({ label: s.label, value: percent(row[s.key] as number) }))}
                />
              );
            }}
          />
          {series.map((s) => (
            <Line
              key={s.key}
              type="monotone"
              dataKey={s.key}
              name={s.label}
              stroke={colors[s.color]}
              strokeWidth={s.emphasis ? 2.5 : 1.5}
              strokeDasharray={s.dashed ? "6 4" : undefined}
              isAnimationActive={false}
              connectNulls
              dot={(props: { cx?: number; cy?: number; index?: number }) => (
                <Mark
                  key={`${s.key}-${props.index}`}
                  shape={s.shape}
                  cx={props.cx ?? 0}
                  cy={props.cy ?? 0}
                  size={s.emphasis ? 5 : 4}
                  color={colors[s.color]}
                  ring={colors.surface}
                />
              )}
              activeDot={false}
            />
          ))}
          {measured.length > 0 && (
            <Scatter
              data={measuredData}
              dataKey="y"
              isAnimationActive={false}
              shape={(props: { cx?: number; cy?: number }) => (
                <Mark shape="triangle" cx={props.cx ?? 0} cy={props.cy ?? 0} color={colors.ink} ring={colors.surface} />
              )}
            >
              <ErrorBar dataKey="error" direction="y" width={8} strokeWidth={2} stroke={colors.ink} />
            </Scatter>
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}
