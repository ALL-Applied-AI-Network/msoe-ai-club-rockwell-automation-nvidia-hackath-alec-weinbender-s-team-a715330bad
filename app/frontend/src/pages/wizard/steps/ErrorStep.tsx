import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, unwrapAs, type Schemas } from "../../../backend/client";
import { useMeta } from "../../../backend/queries";
import { Badge } from "../../../components/Badge";
import { Banner } from "../../../components/Banner";
import { DotGridMap, type DotCategory, type GridDot } from "../../../components/charts/DotGridMap";
import { Checkbox, NumberInput } from "../../../components/Field";
import { RadioCards } from "../../../components/RadioCards";
import { RangeSlider, ValueSlider } from "../../../components/RangeSlider";
import { Segmented } from "../../../components/Segmented";
import { Skeleton } from "../../../components/States";
import { Stat } from "../../../components/Stat";
import { CAVEATS } from "../../../caveats";
import { degrees, mm, percent } from "../../../format";
import { useDraft, useStepGate } from "../draft";
import { useDebounced } from "./useDebounced";
import styles from "./designSteps.module.css";

type ErrorModel = Schemas["ErrorModel"];
type Preset = ErrorModel["preset"];
type Grid = Schemas["GridResponse"];

const STEP = 7;
const SIGMA = { min: 0.1, max: 10, step: 0.05 }; // mm
const YAW = { min: 0, max: 30, step: 0.5 }; // degrees

const CATEGORIES: DotCategory[] = [
  { key: "offset", label: "Offset tested", description: "darker where the camera error puts the part more often", color: "acc", shape: "dot" },
  { key: "bias", label: "Where the bias centres the error", color: "warn", shape: "diamond" },
];

/** Step 7: how far off the camera can be, and the offsets every design is tested at (frontend-plan.md, step 7). The
 *  screen that explains the method: one grid of offsets is simulated, then scored at any error level. */
export function ErrorStep() {
  const { draft, update, plan } = useDraft();
  const meta = useMeta();
  const error = draft.error;
  const setError = (patch: Partial<ErrorModel>) => error && update({ error: { ...error, ...patch } });
  const [yaw, setYaw] = useState("0");

  useStepGate(STEP, error ? { ok: true } : { ok: false, reason: "Choose a camera error" });

  const part = plan.data?.part; // the primary pose's; the grid covers every pose's (yaw layers if any pose needs them)
  const parts = plan.data?.poses.map((p) => p.part) ?? [];
  const request = useDebounced(part && error ? { part, parts, error, final: false } : null, 150);
  const grid = useQuery({
    queryKey: ["grid", request],
    queryFn: () => unwrapAs<Grid>(api.POST("/api/grids", { body: request! })),
    enabled: request !== null,
    placeholderData: keepPreviousData,
  });

  if (!error || !meta.data) return <Skeleton height={360} />;

  const presets = meta.data.error_presets;
  const preset = presets.find((p) => p.name === error.preset);
  const roundFromAbove = part?.shape === "cylinder" && part.axis === "z";
  const pick = (name: Preset) => {
    const chosen = presets.find((p) => p.name === name);
    setError(chosen ? { preset: name, sigma_mm: chosen.sigma_mm, sigma_deg: chosen.sigma_deg } : { preset: "custom" });
  };
  const outer = grid.data?.outer_ring_mm;
  const biasPastRing = outer != null && error.bias_mm + 2 * error.sigma_mm > outer;

  return (
    <div className={styles.split}>
      <div className={styles.column}>
        <RadioCards<Preset>
          label="Camera error"
          columns={2}
          value={error.preset}
          onChange={pick}
          options={[
            ...presets.map((p) => ({
              value: p.name as Preset,
              label: p.label,
              description: `${mm(p.sigma_mm, 2)} sigma, yaw ${degrees(p.sigma_deg, 1)}: ${p.note}.`,
              aside: p.placeholder ? <Badge tone="warn" label="Placeholder" title={CAVEATS.placeholderError} /> : undefined,
            })),
            { value: "custom" as Preset, label: "Custom", description: "Your own numbers, e.g. measured at the cell." },
          ]}
        />
        {preset?.placeholder && <Banner tone="warn">{CAVEATS.placeholderError}</Banner>}

        <div className={styles.panel}>
          <ValueSlider
            label="Position error, 1 sigma"
            {...SIGMA}
            format={(v) => mm(v, 2)}
            value={error.sigma_mm}
            onChange={(sigma_mm) => setError({ sigma_mm, preset: "custom" })}
          />
          <ValueSlider
            label="Yaw error, 1 sigma"
            {...YAW}
            format={(v) => degrees(v, 1)}
            value={error.sigma_deg}
            onChange={(sigma_deg) => setError({ sigma_deg, preset: "custom" })}
            hint={
              roundFromAbove
                ? "This part is round from above, so its yaw doesn't change the grasp."
                : "Only matters for boxes and lying cylinders."
            }
            disabled={roundFromAbove}
          />
        </div>

        <div className={styles.panel}>
          <Checkbox
            label="Design for a range of camera errors"
            checked={error.sigma_range_mm != null}
            onChange={(on) =>
              setError({
                sigma_range_mm: on ? [Math.max(SIGMA.min, round(error.sigma_mm / 2)), Math.min(SIGMA.max, round(error.sigma_mm * 1.5))] : null,
              })
            }
            hint="No extra simulation."
          />
          {error.sigma_range_mm && (
            <RangeSlider
              label="Sigma range"
              {...SIGMA}
              format={(v) => mm(v, 2)}
              value={error.sigma_range_mm}
              onChange={(sigma_range_mm) => setError({ sigma_range_mm })}
              hint="The search favours designs that hold up across the whole range."
            />
          )}
        </div>

        <div className={styles.panel}>
          <h3 className={styles.panelTitle}>Bias (optional)</h3>
          <div className={styles.fields}>
            <NumberInput
              label="Systematic offset"
              unit="mm"
              min={0}
              step={0.1}
              value={error.bias_mm}
              onChange={(value) => setError({ bias_mm: Math.max(0, value ?? 0) })}
              hint="A camera that's always off the same way."
            />
            <NumberInput
              label="Its direction"
              unit="°"
              step={5}
              value={error.bias_direction_deg}
              onChange={(value) => setError({ bias_direction_deg: value ?? 0 })}
              hint="From the jaws' closing direction."
              disabled={error.bias_mm === 0}
            />
          </div>
          {biasPastRing && outer != null && (
            <Banner tone="warn">
              The bias plus 2 sigma reaches {mm(error.bias_mm + 2 * error.sigma_mm)}, past the grid's outer ring at {mm(outer)}:
              grasps out there aren't tested, so the scores flatter the designs.
            </Banner>
          )}
        </div>
      </div>

      <div className={`${styles.column} ${styles.sticky}`}>
        <GridPanel grid={grid.data} loading={!grid.data} error={error} yaw={yaw} onYaw={setYaw} plan={plan.data} />
      </div>
    </div>
  );
}

/** The test grid from above: a dot per offset, darker where the error puts the part more often, with the sigma circles
 *  and the outer ring. */
function GridPanel({
  grid,
  loading,
  error,
  yaw,
  onYaw,
  plan,
}: {
  grid: Grid | undefined;
  loading: boolean;
  error: ErrorModel;
  yaw: string;
  onYaw: (yaw: string) => void;
  plan: Schemas["JobPlan"] | undefined;
}) {
  if (loading || !grid) return <Skeleton height={420} />;
  const layers = grid.yaws_deg;
  const layer = layers.some((y) => String(y) === yaw) ? Number(yaw) : (layers.find((y) => y === 0) ?? layers[0]);
  const points = grid.points.filter((p) => p.yaw_deg === layer);
  const heaviest = Math.max(...points.map((p) => p.weight), 1e-9);
  const biased = error.bias_mm > 0;
  const circle = grid.circles[0];

  const dots: GridDot[] = points.map((p, i) => ({
    key: `${i}`,
    x: p.dx,
    y: p.dy,
    category: "offset",
    weight: p.weight / heaviest,
    title: `Offset ${mm(p.dx)}, ${mm(p.dy)}`,
    details: [{ label: "weight", value: percent(p.weight) }],
  }));
  if (biased && circle) {
    dots.push({ key: "bias", x: circle.centre_mm[0], y: circle.centre_mm[1], category: "bias", title: "Centre of the biased error" });
  }
  const rings = [
    ...(biased ? [] : grid.circles.map((c) => ({ radius: c.radius_mm, label: c.label }))),
    { radius: grid.outer_ring_mm, label: "outer ring" },
  ];

  return (
    <div className={styles.panel}>
      <div className={styles.row}>
        <h3 className={styles.panelTitle}>Test offsets</h3>
        {layers.length > 1 && (
          <Segmented
            label="Yaw layer"
            value={String(layer)}
            onChange={onYaw}
            options={layers.map((y) => ({ value: String(y), label: `yaw ${degrees(y)}` }))}
          />
        )}
      </div>
      <DotGridMap
        dots={dots}
        categories={CATEGORIES}
        rings={rings}
        summary={`${grid.n_offsets} offsets out to ${mm(grid.outer_ring_mm)}, seen from above, weighted by a ${mm(error.sigma_mm, 2)} camera error${biased ? ` biased ${mm(error.bias_mm)} at ${degrees(error.bias_direction_deg)}` : ""}.`}
        note="Changing sigma never needs new simulations: results re-score at any sigma."
      />
      {biased && <p className={styles.note}>With a bias, the sigma circles sit around the diamond, not the centre.</p>}
      <div className={styles.fields}>
        <Stat label="Offsets per design" value={grid.n_offsets} detail={layers.length > 1 ? `${layers.length} yaw layers` : "one yaw"} />
        <Stat label="Error inside the grid" value={percent(grid.coverage)} detail={`out to ${mm(grid.covered_to_mm)}`} />
        {plan && <Stat label="Grasps in the run" value={plan.totals.total_grasps.toLocaleString()} detail={`final test: ${plan.totals.final_offsets} offsets`} />}
      </div>
      {layers.length > 1 && <p className={styles.note}>Testing yaw multiplies the offsets by the {layers.length} layers.</p>}
      {grid.warnings.map((w) => (
        <Banner key={w} tone="warn">
          {w.charAt(0).toUpperCase() + w.slice(1)}.
        </Banner>
      ))}
    </div>
  );
}

function round(value: number): number {
  return Math.round(value * 20) / 20;
}
