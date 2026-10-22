import type { ReactNode } from "react";
import {
  CartesianGrid,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  useXAxisScale,
  useYAxisScale,
} from "recharts";
import { mm } from "../../format";
import { ChartFrame, ChartTooltip, type LegendItem } from "./ChartFrame";
import { axisProps, useChartColors, type ChartColor } from "./chartColors";
import { Mark, type MarkShapeName } from "./MarkShape";

export type DotCategory = {
  key: string;
  label: string;
  description?: string; // what it means, in words; shown in the legend
  color: ChartColor;
  shape: MarkShapeName;
};

export type GridDot = {
  key: string;
  x: number; // offset in mm
  y: number;
  category: string; // a DotCategory key
  weight?: number; // 0 to 1: the dot's opacity, e.g. its weight under the camera-error model; 1 when unset
  title: string; // the tooltip's heading
  details?: { label: string; value: ReactNode }[]; // more tooltip rows
};

type DotGridMapProps = {
  dots: GridDot[];
  categories: DotCategory[];
  summary: string; // the text alternative
  rings?: { radius: number; label: string }[]; // circles around the centre, e.g. 1 and 2 sigma, in mm
  xLabel?: string;
  yLabel?: string;
  note?: ReactNode;
  onDotClick?: (dot: GridDot) => void; // makes the dots pickable, e.g. a held-map grasp to film in Isaac Sim
};

/** Grasp offsets seen from above, one marker per offset tested: held maps, the validation mismatch map, the test grid.
 *  Both axes are in mm on the same scale, so the map isn't stretched. Each category has its own colour and shape. */
export function DotGridMap({
  dots,
  categories,
  summary,
  rings = [],
  xLabel = "Offset x, the jaws' closing direction",
  yLabel = "Offset y",
  note,
  onDotClick,
}: DotGridMapProps) {
  const colors = useChartColors();
  const byKey = new Map(categories.map((c) => [c.key, c]));
  const reach = Math.max(1, ...dots.map((d) => Math.max(Math.abs(d.x), Math.abs(d.y))), ...rings.map((r) => r.radius));
  const limit = Math.ceil(reach + 0.5);
  const ticks = niceTicks(limit);
  const label = { fill: colors.faint, fontSize: 12 };
  const legend: LegendItem[] = categories
    .filter((c) => dots.some((d) => d.category === c.key))
    .map(({ label: name, description, color, shape }) => ({ label: name, description, color, shape }));

  return (
    <ChartFrame summary={summary} legend={legend} note={note}>
      <ResponsiveContainer width="100%" aspect={1.08} maxHeight={520}>
        <ScatterChart margin={{ top: 12, right: 16, bottom: 28, left: 12 }}>
          <CartesianGrid stroke={colors.line} />
          <XAxis
            type="number"
            dataKey="x"
            domain={[-limit, limit]}
            ticks={ticks}
            tickFormatter={(v: number) => String(v)}
            label={{ value: `${xLabel} (mm)`, position: "insideBottom", offset: -18, ...label }}
            {...axisProps(colors)}
          />
          <YAxis
            type="number"
            dataKey="y"
            domain={[-limit, limit]}
            ticks={ticks}
            tickFormatter={(v: number) => String(v)}
            label={{ value: `${yLabel} (mm)`, angle: -90, position: "insideLeft", offset: 4, ...label }}
            width={56}
            {...axisProps(colors)}
          />
          {rings.map((ring) => (
            <Ring key={ring.label} radius={ring.radius} label={ring.label} stroke={colors["line-strong"]} text={colors.faint} />
          ))}
          <Tooltip
            cursor={false}
            content={({ active, payload }) => {
              const dot = payload?.[0]?.payload as GridDot | undefined;
              if (!active || !dot) return null;
              return (
                <ChartTooltip
                  title={dot.title}
                  rows={[
                    { label: "status", value: byKey.get(dot.category)?.label ?? dot.category },
                    { label: "offset", value: `${mm(dot.x)}, ${mm(dot.y)}` },
                    ...(dot.details ?? []),
                  ]}
                />
              );
            }}
          />
          <Scatter
            data={dots}
            isAnimationActive={false}
            shape={(props: { cx?: number; cy?: number; payload?: GridDot }) => {
              const category = props.payload && byKey.get(props.payload.category);
              if (!category) return <g />;
              return (
                <g
                  opacity={0.35 + 0.65 * (props.payload?.weight ?? 1)}
                  style={onDotClick ? { cursor: "pointer" } : undefined}
                  onClick={onDotClick && props.payload ? () => onDotClick(props.payload!) : undefined}
                >
                  <circle cx={props.cx} cy={props.cy} r={12} fill="transparent" />
                  <Mark
                    shape={category.shape}
                    cx={props.cx ?? 0}
                    cy={props.cy ?? 0}
                    color={colors[category.color]}
                    ring={colors.surface}
                  />
                </g>
              );
            }}
          />
        </ScatterChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}

/** A circle of the given radius in mm around the centre, drawn in the chart's own scales. */
function Ring({ radius, label, stroke, text }: { radius: number; label: string; stroke: string; text: string }) {
  const x = useXAxisScale();
  const y = useYAxisScale();
  if (!x || !y) return null;
  const cx = x(0) as number;
  const cy = y(0) as number;
  const rx = Math.abs((x(radius) as number) - cx);
  const ry = Math.abs((y(radius) as number) - cy);
  return (
    <g>
      <ellipse cx={cx} cy={cy} rx={rx} ry={ry} fill="none" stroke={stroke} strokeWidth={1} />
      <text x={cx + rx * 0.71 + 4} y={cy - ry * 0.71 - 4} fill={text} fontSize={11}>
        {label}
      </text>
    </g>
  );
}

function niceTicks(limit: number): number[] {
  const step = limit <= 4 ? 1 : limit <= 10 ? 2 : limit <= 20 ? 5 : 10;
  const ticks: number[] = [];
  for (let v = -Math.floor(limit / step) * step; v <= limit; v += step) ticks.push(v);
  return ticks;
}
