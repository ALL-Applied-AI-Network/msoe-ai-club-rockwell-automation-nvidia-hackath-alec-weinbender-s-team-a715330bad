import { Card } from "../../../components/Card";
import { BinChart, type Bin } from "../../../components/charts/BinChart";
import { Stat } from "../../../components/Stat";
import { degrees, mm, percent } from "../../../format";
import { designLabel } from "../../../labels";
import type { Results } from "../types";
import styles from "../JobPage.module.css";

/** How the part sits in the hand after the lift, against the task's tolerance (place and insert only): a held part
 *  that sits too far off still fails the task. */
export function InHand({ results }: { results: Results }) {
  const view = results.in_hand!;
  const offsetTol = view.offset_tolerance_mm;
  const tiltTol = view.tilt_tolerance_deg;
  return (
    <Card
      title="How the part sits in the hand"
      subtitle={`${designLabel(view.label)}'s held grasps: where the part sits against where the task expects it, weighted by likelihood.`}
    >
      <div className={styles.stats}>
        <Stat label="Held grasps" value={String(view.n_held)} />
        {view.within_tolerance != null && (
          <Stat label="Within tolerance" value={percent(view.within_tolerance)} tone="acc" detail="of held grasps, weighted" />
        )}
      </div>
      <div className={styles.pair}>
        <BinChart
          bins={histogram(view.offsets_mm, view.weights, offsetTol)}
          xLabel="Offset in the hand (mm)"
          yLabel="Share of held grasps"
          formatX={(x) => `about ${mm(x, 2)}`}
          reference={offsetTol != null ? { x: snap(offsetTol, view.offsets_mm), label: `Tolerance ${mm(offsetTol)}` } : undefined}
          summary={`Offsets in the hand for ${view.n_held} held grasps${offsetTol != null ? `, against a ${mm(offsetTol)} tolerance` : ""}.`}
        />
        {tiltTol != null && (
          <BinChart
            bins={histogram(view.tilts_deg, view.weights, tiltTol)}
            xLabel="Tilt in the hand (°)"
            yLabel="Share of held grasps"
            formatX={(x) => `about ${degrees(x, 1)}`}
            reference={{ x: snap(tiltTol, view.tilts_deg), label: `Tolerance ${degrees(tiltTol)}` }}
            summary={`Tilts in the hand for ${view.n_held} held grasps, against a ${degrees(tiltTol)} tolerance.`}
          />
        )}
      </div>
    </Card>
  );
}

const BINS = 12;

/** Weighted shares in equal bins from 0 to past the tolerance; bins past it in the warn tone. */
function histogram(values: number[], weights: number[], tolerance: number | null): Bin[] {
  const top = Math.max(tolerance ?? 0, ...values, 0.1) * 1.1;
  const width = top / BINS;
  const total = weights.reduce((sum, w) => sum + w, 0) || 1;
  const sums = new Array<number>(BINS).fill(0);
  values.forEach((v, i) => {
    sums[Math.min(BINS - 1, Math.floor(Math.abs(v) / width))] += weights[i] ?? 0;
  });
  return sums.map((sum, i) => {
    const x = Number(((i + 0.5) * width).toFixed(2));
    return { key: String(i), x, value: sum / total, color: tolerance != null && x > tolerance ? "warn" : "acc" };
  });
}

/** The bin centre nearest the tolerance, so the reference line lands on the category axis. */
function snap(tolerance: number, values: number[]): number {
  const bins = histogram(values, values.map(() => 1), tolerance);
  return bins.reduce((best, b) => (Math.abs(b.x - tolerance) < Math.abs(best.x - tolerance) ? b : best), bins[0]).x;
}
