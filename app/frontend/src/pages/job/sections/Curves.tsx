import { Card } from "../../../components/Card";
import { SuccessCurveChart, type CurveSeries } from "../../../components/charts/SuccessCurveChart";
import { mm, percent } from "../../../format";
import { designLabel } from "../../../labels";
import type { Results } from "../types";

/** Success against camera error for every final design and the baselines (frontend-plan.md 7.1): the core claim, and
 *  where the robot's measured points meet the prediction. */
export function Curves({ results }: { results: Results }) {
  const curves = results.curves!;
  const leader = results.summary?.leader;
  const searched = curves.designs.filter((d) => d.kind === "search" || d.kind === "locked");
  const series: CurveSeries[] = curves.designs.map((d) => {
    const points = curves.sigmas_mm
      .map((sigma) => ({ sigma, success: lookup(d.success, sigma) }))
      .filter((p): p is { sigma: number; success: number } => p.success != null);
    const base = { key: d.label, label: designLabel(d.label), points };
    if (d.kind === "stock") return { ...base, color: "baseline", shape: "square", dashed: true };
    if (d.kind === "imprint") return { ...base, color: "neutral", shape: "diamond", dashed: true };
    if (d.label === leader) return { ...base, color: "acc", shape: "dot", emphasis: true };
    return { ...base, color: "faint", shape: "ring" };
  });
  // The leader first in the legend, then the other designs, then the baselines.
  const order = (s: CurveSeries) => (s.key === leader ? 0 : s.dashed ? 2 : 1);
  series.sort((a, b) => order(a) - order(b));

  const measured = results.physical.curve_points.map((p) => ({
    key: `${p.design_label}-${p.sigma_mm}`,
    label: designLabel(p.design_label),
    sigma: p.sigma_mm,
    success: p.measured_success,
    low: p.wilson_low,
    high: p.wilson_high,
    n: p.n,
  }));
  const target = curves.target_sigma_mm;
  const at = (key: string) => {
    const d = curves.designs.find((c) => c.label === key);
    return d ? lookup(d.success, target) : null;
  };
  const leaderAt = leader ? at(leader) : null;
  const stockAt = at("STOCK");

  return (
    <Card
      title="Success against camera error"
      subtitle={`How each finger holds up as the camera's position error grows. The target, σ ${mm(target)}, is marked${
        curves.target_range_mm ? `, with the range it was designed for shaded` : ""
      }. ${searched.length > 1 ? "The leading design is the heavy line." : ""}`}
    >
      <SuccessCurveChart
        series={series}
        measured={measured}
        target={target}
        targetRange={curves.target_range_mm}
        summary={`Predicted success against camera error from ${mm(curves.sigmas_mm[0] ?? 0)} to ${mm(
          curves.sigmas_mm.at(-1) ?? 0,
        )}. At the target ${mm(target)}${
          leader && leaderAt != null ? `, ${designLabel(leader)} holds ${percent(leaderAt)}` : ""
        }${stockAt != null ? ` and the stock fingers ${percent(stockAt)}` : ""}.${
          measured.length ? ` ${measured.length} points measured on the robot are shown with their 95% intervals.` : ""
        }`}
        note={
          measured.length
            ? "Triangles are success measured on the robot, with the 95% interval of the trials behind them."
            : "Measured points from the robot appear here once physical trials are logged."
        }
      />
    </Card>
  );
}

/** A curve's success at a sigma. The keys are the sigmas as the API writes them ("0.5", "1", "2"). */
function lookup(success: Record<string, number>, sigma: number): number | null {
  return success[String(sigma)] ?? success[sigma.toFixed(1)] ?? null;
}
