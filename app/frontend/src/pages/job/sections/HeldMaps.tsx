import { useState } from "react";
import { Card } from "../../../components/Card";
import { DotGridMap, type DotCategory, type GridDot } from "../../../components/charts/DotGridMap";
import { Segmented } from "../../../components/Segmented";
import { CAVEATS } from "../../../caveats";
import { degrees, mm, percent } from "../../../format";
import { designLabel } from "../../../labels";
import type { ClipPick, Results } from "../types";
import styles from "../JobPage.module.css";

const CATEGORIES: DotCategory[] = [
  { key: "held", label: "Held", description: "held through the lift", color: "ok", shape: "dot" },
  { key: "missed", label: "Missed", description: "dropped, or never caught", color: "bad", shape: "triangle" },
];

/** Every offset of the final grid, held or missed, the best design beside the stock fingers (frontend-plan.md 7.1):
 *  error tolerance made visible. Dots fade with their weight under the camera-error model. With Isaac results, a click
 *  picks that grasp to film. */
export function HeldMaps({ results, onPick }: { results: Results; onPick?: (pick: ClipPick) => void }) {
  const all = results.held_maps;
  const yaws = [...new Set(all.flatMap((m) => m.points.map((p) => p.yaw_deg)))].sort((a, b) => a - b);
  const [yaw, setYaw] = useState(yaws.includes(0) ? 0 : (yaws[0] ?? 0));
  // A job with several resting poses has maps per pose (null for one pose); the first is the primary.
  const poses = [...new Map(all.filter((m) => m.pose).map((m) => [m.pose!, m.pose_label ?? m.pose!])).entries()];
  const [pose, setPose] = useState<string | null>(poses[0]?.[0] ?? null);
  const maps = pose ? all.filter((m) => m.pose === pose) : all;
  const primary = !pose || pose === poses[0]?.[0]; // clips film the primary pose only
  const sigma = results.header.error.sigma_mm;
  const rings = [
    { radius: sigma, label: "1σ" },
    { radius: 2 * sigma, label: "2σ" },
  ];

  return (
    <Card
      title="Held maps"
      subtitle="Each dot is one offset of the final grid, seen from above."
      aside={
        <div className={styles.row}>
          {poses.length > 1 && (
            <Segmented
              label="Resting pose"
              value={pose ?? ""}
              onChange={setPose}
              options={poses.map(([key, label]) => ({ value: key, label: label.charAt(0).toUpperCase() + label.slice(1) }))}
            />
          )}
          {yaws.length > 1 && (
            <Segmented
              label="Yaw layer"
              value={String(yaw)}
              onChange={(value) => setYaw(Number(value))}
              options={yaws.map((y) => ({ value: String(y), label: `Yaw ${degrees(y)}` }))}
            />
          )}
        </div>
      }
    >
      <div className={styles.pair}>
        {maps.map((map) => {
          const points = map.points.filter((p) => p.yaw_deg === yaw);
          const top = Math.max(...points.map((p) => p.weight), 1e-9);
          const held = points.filter((p) => p.held).length;
          const dots: GridDot[] = points.map((p, i) => ({
            key: `${i}`,
            x: p.dx,
            y: p.dy,
            category: p.held ? "held" : "missed",
            weight: p.weight / top,
            title: `${designLabel(map.label)} at ${mm(p.dx)}, ${mm(p.dy)}`,
            details: [
              { label: "task", value: p.success ? "success" : "not a success" },
              { label: "weight", value: percent(p.weight / top) },
            ],
          }));
          return (
            <div key={`${map.label}-${map.pose ?? ""}`}>
              <div className={styles.mapTitle}>
                {designLabel(map.label)}: held {held} of {points.length}
              </div>
              <DotGridMap
                dots={dots}
                categories={CATEGORIES}
                rings={rings}
                summary={`${designLabel(map.label)} held ${held} of ${points.length} offsets at yaw ${degrees(yaw)}.`}
                onDotClick={
                  onPick && primary
                    ? (dot) => {
                        const p = points[Number(dot.key)];
                        onPick({ design: map.label, offset: { dx: p.dx, dy: p.dy, yaw_deg: p.yaw_deg } });
                      }
                    : undefined
                }
              />
            </div>
          );
        })}
      </div>
      <p className={styles.note}>
        {CAVEATS.captureEdge} The circles are 1σ and 2σ of the target camera error, σ {mm(sigma)}.
        {onPick && primary ? " Click a dot to film that grasp in Isaac Sim." : ""}
      </p>
    </Card>
  );
}
