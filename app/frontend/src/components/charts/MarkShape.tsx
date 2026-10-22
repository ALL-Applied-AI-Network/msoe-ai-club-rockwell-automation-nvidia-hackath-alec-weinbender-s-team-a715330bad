// The marker shapes charts use. Shape is the second channel next to colour, so categories whose colours sit close for
// colour-blind readers (ok green and warn amber) still read apart, and the legend shows the same shape.

export type MarkShapeName = "dot" | "ring" | "square" | "diamond" | "triangle";

type MarkProps = {
  shape: MarkShapeName;
  cx: number;
  cy: number;
  color: string;
  ring: string; // the surface colour: a 2 px ring keeps overlapping marks legible
  size?: number; // radius in px; at least 4
};

/** One marker, centred on (cx, cy). */
export function Mark({ shape, cx, cy, color, ring, size = 5 }: MarkProps) {
  const r = size;
  const common = { stroke: ring, strokeWidth: 2, paintOrder: "stroke" as const };
  switch (shape) {
    case "ring":
      return <circle cx={cx} cy={cy} r={r - 1} fill="none" stroke={color} strokeWidth={2} />;
    case "square":
      return <rect x={cx - r} y={cy - r} width={2 * r} height={2 * r} rx={1.5} fill={color} {...common} />;
    case "diamond": {
      const d = r * 1.3;
      return <path d={`M${cx} ${cy - d}L${cx + d} ${cy}L${cx} ${cy + d}L${cx - d} ${cy}Z`} fill={color} {...common} />;
    }
    case "triangle": {
      const d = r * 1.25;
      return <path d={`M${cx} ${cy - d}L${cx + d} ${cy + d * 0.8}L${cx - d} ${cy + d * 0.8}Z`} fill={color} {...common} />;
    }
    default:
      return <circle cx={cx} cy={cy} r={r} fill={color} {...common} />;
  }
}

/** A marker on its own, for legends: the same shape and colour as on the chart. */
export function MarkSwatch({ shape, color, ring }: { shape: MarkShapeName; color: string; ring: string }) {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
      <Mark shape={shape} cx={8} cy={8} color={color} ring={ring} />
    </svg>
  );
}
