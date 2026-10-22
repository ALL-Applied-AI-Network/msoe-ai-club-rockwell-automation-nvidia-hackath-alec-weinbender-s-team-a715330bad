import { CartesianGrid, ErrorBar, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from "recharts";
import { percent } from "../../format";
import { ChartFrame, ChartTooltip } from "./ChartFrame";
import { axisProps, useChartColors } from "./chartColors";
import { Mark } from "./MarkShape";

export type ParityPoint = {
  key: string;
  title: string; // the tooltip's heading, e.g. "EXP-0001, D1"
  predicted: number; // 0 to 1
  measured: number; // 0 to 1
  low?: number | null; // the measured rate's 95% interval
  high?: number | null;
  n?: number;
};

type ParityScatterProps = {
  points: ParityPoint[];
  summary: string; // the text alternative
  note?: string;
};

/** Predicted against measured success, one dot per design, with the diagonal where the sim matches reality. Dots above
 *  the line did better on the robot than the sim said; dots below did worse. One series, so no legend: the axes say it. */
export function ParityScatter({ points, summary, note }: ParityScatterProps) {
  const colors = useChartColors();
  const data = points.map((p) => ({
    ...p,
    error: [p.measured - (p.low ?? p.measured), (p.high ?? p.measured) - p.measured],
  }));
  const label = { fill: colors.faint, fontSize: 12 };

  return (
    <ChartFrame summary={summary} note={note}>
      <ResponsiveContainer width="100%" aspect={1.25} maxHeight={460}>
        <ScatterChart margin={{ top: 12, right: 24, bottom: 28, left: 12 }}>
          <CartesianGrid stroke={colors.line} />
          <XAxis
            type="number"
            dataKey="predicted"
            domain={[0, 1]}
            ticks={[0, 0.25, 0.5, 0.75, 1]}
            tickFormatter={(v: number) => percent(v)}
            label={{ value: "Predicted by the sim", position: "insideBottom", offset: -18, ...label }}
            {...axisProps(colors)}
          />
          <YAxis
            type="number"
            dataKey="measured"
            domain={[0, 1]}
            ticks={[0, 0.25, 0.5, 0.75, 1]}
            tickFormatter={(v: number) => percent(v)}
            label={{ value: "Measured on the robot", angle: -90, position: "insideLeft", offset: 4, ...label }}
            width={64}
            {...axisProps(colors)}
          />
          <ReferenceLine
            segment={[
              { x: 0, y: 0 },
              { x: 1, y: 1 },
            ]}
            stroke={colors["line-strong"]}
            strokeWidth={1}
            label={{ value: "Sim matches the robot", position: "insideTopLeft", ...label }}
          />
          <Tooltip
            cursor={false}
            content={({ active, payload }) => {
              const point = payload?.[0]?.payload as ParityPoint | undefined;
              if (!active || !point) return null;
              return (
                <ChartTooltip
                  title={point.title}
                  rows={[
                    { label: "predicted", value: percent(point.predicted) },
                    { label: "measured", value: percent(point.measured) },
                    ...(point.low != null && point.high != null
                      ? [{ label: "95% interval", value: `${percent(point.low)} to ${percent(point.high)}` }]
                      : []),
                    ...(point.n != null ? [{ label: "trials", value: point.n }] : []),
                  ]}
                />
              );
            }}
          />
          <Scatter
            data={data}
            isAnimationActive={false}
            shape={(props: { cx?: number; cy?: number }) => (
              <g>
                <circle cx={props.cx} cy={props.cy} r={12} fill="transparent" />
                <Mark shape="dot" cx={props.cx ?? 0} cy={props.cy ?? 0} color={colors.acc} ring={colors.surface} />
              </g>
            )}
          >
            <ErrorBar dataKey="error" direction="y" width={6} strokeWidth={1.5} stroke={colors.acc} />
          </Scatter>
        </ScatterChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}
