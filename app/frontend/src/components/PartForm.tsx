import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, unwrapAs, type Schemas } from "../backend/client";
import { useMeta } from "../backend/queries";
import { CAVEATS } from "../caveats";
import { mass, quantity, toGrams, trim } from "../format";
import { Banner } from "./Banner";
import { Button } from "./Button";
import { Checkbox, NumberInput } from "./Field";
import { Select } from "./Select";
import styles from "./PartForm.module.css";

type Part = Schemas["PartResponse"];
type Update = Schemas["UpdatePartRequest"];
type Material = NonNullable<Part["material"]>;
type MassUnit = Part["mass_unit"];

// The twin grips with about 2.5 N per jaw (CONTEXT.md, risk 6): parts over about 100 g, or with a static friction
// against the pad below about 0.35 (an oily surface on most materials), score as dropped for every design.
const WEAK_GRIP_MASS_G = 100;
const WEAK_GRIP_FRICTION = 0.35;

/** Whether the twin's weak grip will drop this part whatever the fingers (a warning, never a block). */
export function weakGrip(part: Part): boolean {
  return (part.confirmed_mass_g ?? 0) > WEAK_GRIP_MASS_G || part.friction_vs_pad[0] < WEAK_GRIP_FRICTION;
}

/** A part's material, surface, mass and handling: the Parts page, and the wizard's step 1. Saves only what changed
 *  (PATCH). Give it `key={part.id}` so switching parts starts a fresh form. */
export function PartForm({ part, onSaved }: { part: Part; onSaved?: (part: Part) => void }) {
  const meta = useMeta();
  const queryClient = useQueryClient();
  const [material, setMaterial] = useState<Material | "">(part.material ?? part.measured.material_hint ?? "");
  const [density, setDensity] = useState<number | null>(part.density_g_cm3 ?? null);
  const [surface, setSurface] = useState(part.surface);
  const [unit, setUnit] = useState<MassUnit>(part.mass_unit);
  const [measured, setMeasured] = useState(part.mass_source === "measured");
  const [massG, setMassG] = useState<number | null>(part.mass_g ?? null); // the measured mass, always in grams
  const [fragile, setFragile] = useState(part.fragile);
  const [maxForce, setMaxForce] = useState<number | null>(part.max_grip_force_n ?? null);
  const [clearance, setClearance] = useState<number | null>(part.clearance_mm ?? null);

  const save = useMutation({
    mutationFn: (body: Update) =>
      unwrapAs<Part>(api.PATCH("/api/parts/{part_id}", { params: { path: { part_id: part.id } }, body })),
    onSuccess: (saved) => {
      queryClient.setQueryData(["parts", saved.id], saved);
      void queryClient.invalidateQueries({ queryKey: ["parts"], exact: true });
      onSaved?.(saved);
    },
  });

  const materials = meta.data?.materials ?? [];
  const info = materials.find((m) => m.name === material);
  const isOther = material === "other";
  const liveDensity = isOther ? density : (info?.density_g_cm3 ?? null);
  const computedG = liveDensity ? (part.measured.volume_mm3 / 1000) * liveDensity : null;
  const perUnit = toGrams(1, unit);

  // Only what changed goes in the PATCH.
  const body: Update = {};
  if (material && material !== part.material) {
    body.material = material;
    body.density_g_cm3 = isOther ? density : null; // a new material drops an earlier density
  } else if (isOther && density !== (part.density_g_cm3 ?? null)) body.density_g_cm3 = density;
  if (surface !== part.surface) body.surface = surface;
  if (unit !== part.mass_unit) body.mass_unit = unit;
  const wantedMass = measured ? massG : null;
  if (wantedMass !== (part.mass_g ?? null)) body.mass_g = wantedMass;
  if (fragile !== part.fragile) body.fragile = fragile;
  if (fragile && maxForce !== (part.max_grip_force_n ?? null)) body.max_grip_force_n = maxForce;
  if (clearance !== (part.clearance_mm ?? null)) body.clearance_mm = clearance;
  const changed = Object.keys(body).length > 0;

  const errors = {
    material: material ? undefined : "Choose the material.",
    density: isOther && !(density && density > 0) ? "Other needs a density." : undefined,
    mass: measured && !(massG && massG > 0) ? "Type the measured mass, or use the computed one." : undefined,
    maxForce: maxForce != null && maxForce <= 0 ? "A grip force is more than 0 N." : undefined,
    clearance: clearance != null && clearance < 0 ? "A clearance can't be negative." : undefined,
  };
  const valid = Object.values(errors).every((error) => !error);

  return (
    <form
      className={styles.form}
      onSubmit={(event) => {
        event.preventDefault();
        if (changed && valid) save.mutate(body);
      }}
    >
      {weakGrip(part) && (
        <Banner tone="warn" title="Weak grip">
          {CAVEATS.weakGrip}
        </Banner>
      )}

      <div className={styles.grid}>
        <Select
          label="Material"
          value={material}
          placeholder={material ? undefined : "Choose the material"}
          onChange={(event) => setMaterial(event.target.value as Material)}
          options={materials.map((m) => ({ value: m.name, label: m.label }))}
          error={changed ? errors.material : undefined} // only once there's something to save that it blocks
          hint={
            !part.material && part.measured.material_hint
              ? "From the CAD file. Save to confirm."
              : info?.density_g_cm3
                ? `Density ${quantity(info.density_g_cm3, "g/cm³")}`
                : undefined
          }
        />
        <Select
          label="Surface"
          value={surface}
          onChange={(event) => setSurface(event.target.value as Part["surface"])}
          options={(meta.data?.surfaces ?? []).map((s) => ({ value: s.name, label: s.label }))}
          hint={`Friction against the pad: ${trim(part.friction_vs_pad[0])} static, ${trim(part.friction_vs_pad[1])} dynamic`}
        />
        {isOther && (
          <NumberInput label="Density" unit="g/cm³" value={density} onChange={setDensity} min={0} step={0.01} error={errors.density} />
        )}
      </div>

      <fieldset className={styles.group}>
        <legend className={styles.legend}>Mass</legend>
        <p className={styles.computed}>
          {computedG != null
            ? `Computed: ${mass(computedG, unit)}, from ${quantity(part.measured.volume_mm3 / 1000, "cm³")}.`
            : "Choose a material to compute the mass."}{" "}
          {!measured && computedG != null && <strong className={styles.used}>In use.</strong>}
        </p>
        <div className={styles.grid}>
          <Select
            label="Show masses in"
            value={unit}
            onChange={(event) => setUnit(event.target.value as MassUnit)}
            options={(meta.data?.mass_units ?? []).map((u) => ({ value: u.name, label: u.name }))}
          />
          <div className={styles.measured}>
            <Checkbox
              label="Use a measured mass instead"
              checked={measured}
              onChange={setMeasured}
            />
          </div>
          {measured && (
            <NumberInput
              label="Measured mass"
              unit={unit}
              value={massG == null ? null : Number((massG / perUnit).toPrecision(4))}
              onChange={(value) => setMassG(value == null ? null : toGrams(value, unit))}
              min={0}
              step="any"
              error={errors.mass}
              hint="In use."
            />
          )}
        </div>
      </fieldset>

      <fieldset className={styles.group}>
        <legend className={styles.legend}>Handling</legend>
        <div className={styles.grid}>
          <div className={styles.measured}>
            <Checkbox label="Fragile" checked={fragile} onChange={setFragile} />
          </div>
          {fragile && (
            <NumberInput
              label="Max grip force"
              unit="N"
              value={maxForce}
              onChange={setMaxForce}
              min={0}
              step="any"
              error={errors.maxForce}
              hint="Optional"
            />
          )}
          <NumberInput
            label="Clearance to neighbours"
            unit="mm"
            value={clearance}
            onChange={setClearance}
            min={0}
            step="any"
            error={errors.clearance}
            hint="Optional: free space beside the part"
          />
        </div>
      </fieldset>

      <div className={styles.footer}>
        {save.error && <p className={styles.error}>{save.error.message}</p>}
        {save.isSuccess && !changed && <p className={styles.saved}>Saved.</p>}
        <Button type="submit" disabled={!changed || !valid || save.isPending}>
          {save.isPending ? "Saving" : "Save"}
        </Button>
      </div>
    </form>
  );
}
