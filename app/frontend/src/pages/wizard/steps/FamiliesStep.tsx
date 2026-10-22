import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { api, unwrapAs, type Schemas } from "../../../backend/client";
import { useMeta } from "../../../backend/queries";
import { Banner } from "../../../components/Banner";
import { Checkbox, NumberInput } from "../../../components/Field";
import { FingerViewer, type FingerShape } from "../../../components/FingerViewer";
import { RangeSlider } from "../../../components/RangeSlider";
import { Skeleton } from "../../../components/States";
import { Table } from "../../../components/Table";
import { duration, mm, paramValue } from "../../../format";
import { paramLabel, searchMethodLabel } from "../../../labels";
import { useDraft, useStepGate, type Plan } from "../draft";
import { useDebounced } from "./useDebounced";
import styles from "./designSteps.module.css";

type FamilyChoice = Schemas["FamilyChoice"];
type FamilyName = FamilyChoice["family"];
type Param = Schemas["ParamSummary"];
type Part = Schemas["Part"];
type Preview = Schemas["FingerPreviewResponse"];
type Search = Schemas["SearchConfig"];

const STEP = 6;
const DEFAULT_FAMILIES: FamilyChoice[] = [{ family: "vpad", ranges: {}, locks: {} }];

/** Step 6: which finger shapes are searched, over which ranges (frontend-plan.md, step 6). The plan is the source of
 *  truth for each parameter's buildable limits and default range; the user narrows or locks them. */
export function FamiliesStep() {
  const { draft, update, plan } = useDraft();
  const meta = useMeta();
  const families = draft.families ?? DEFAULT_FAMILIES;
  const setFamilies = (next: FamilyChoice[]) => update({ families: next });
  const [focus, setFocus] = useState<{ family: FamilyName; name: string } | null>(null);

  useStepGate(STEP, families.length > 0 ? { ok: true } : { ok: false, reason: "Choose at least one finger family" });

  const profile = useQuery({
    queryKey: ["cell-profiles", draft.cell_profile_id],
    queryFn: () =>
      unwrapAs<Schemas["CellProfileResponse"]>(
        api.GET("/api/cell-profiles/{profile_id}", { params: { path: { profile_id: draft.cell_profile_id! } } }),
      ),
    enabled: draft.cell_profile_id != null,
  });

  const toggle = (family: FamilyName, on: boolean) =>
    setFamilies(on ? [...families, { family, ranges: {}, locks: {} }] : families.filter((f) => f.family !== family));
  const change = (family: FamilyName, edit: (choice: FamilyChoice) => FamilyChoice) =>
    setFamilies(families.map((f) => (f.family === family ? edit(f) : f)));

  const data = plan.data;
  const stepBlockers = data?.blockers.filter((b) => b.step === STEP) ?? [];
  // The preview follows the focused slider; a family unticked under it falls back to the first family's slack.
  const focused = focus && families.some((f) => f.family === focus.family) ? focus : null;
  const previewChoice = families.find((f) => f.family === focused?.family) ?? families[0];
  const previewParams = data?.families.find((f) => f.family === previewChoice?.family)?.params ?? [];
  const previewParam = previewParams.find((p) => p.name === (focused?.name ?? "slack_mm"));

  return (
    <div className={styles.split}>
      <div className={styles.column}>
        <div className={styles.panel}>
          <h3 className={styles.panelTitle}>Finger families</h3>
          {meta.data?.families.map((info) => {
            const built = info.status === "built";
            const name = info.name as FamilyName;
            return (
              <Checkbox
                key={info.name}
                label={built ? info.label : `${info.label} (planned)`}
                checked={built && families.some((f) => f.family === name)}
                disabled={!built}
                onChange={(on) => toggle(name, on)}
                hint={capitalise(info.description) + (info.only_for ? `. For ${info.only_for} only.` : ".")}
              />
            );
          })}
          {families.length === 0 && <p className={styles.error}>Choose at least one family to search.</p>}
        </div>

        {stepBlockers.map((b) => (
          <Banner key={b.reason} tone="bad">
            {b.reason}
          </Banner>
        ))}
        {plan.error && <Banner tone="bad">{plan.error.message}</Banner>}
        {!data && !plan.error && (draft.grasp ? <Skeleton height={320} /> : <Banner tone="warn">Choose the grasp (step 5) first.</Banner>)}

        {data &&
          families.map((choice) => {
            const summary = data.families.find((f) => f.family === choice.family);
            if (!summary) return null;
            const schema = meta.data?.families.find((f) => f.name === choice.family)?.params_schema;
            const applicable = summary.params.filter((p) => p.applies);
            const allLocked = applicable.length > 0 && applicable.every((p) => choice.locks[p.name] != null);
            return (
              <div key={choice.family} className={styles.panel}>
                <h3 className={styles.panelTitle}>{summary.label} parameters</h3>
                {allLocked && (
                  <Banner tone="info" title="Testing one design: every parameter is fixed.">
                    The run evaluates this one finger against the stock fingers and the imprint, instead of searching.
                  </Banner>
                )}
                {summary.warnings.map((w) => (
                  <Banner key={w} tone="warn">
                    {capitalise(w)}.
                  </Banner>
                ))}
                <div className={styles.params}>
                  {summary.params.map((param) => (
                    <ParamRow
                      key={param.name}
                      param={param}
                      choice={choice}
                      appliesTo={appliesTo(schema, param.name)}
                      closedGap={
                        param.name === "slack_mm" && profile.data
                          ? closedGapText(choice, param, data.part, profile.data.profile.stroke_per_jaw_mm)
                          : undefined
                      }
                      onChange={(edit) => change(choice.family, edit)}
                      onFocus={(focused) => focused && setFocus({ family: choice.family, name: param.name })}
                    />
                  ))}
                </div>
              </div>
            );
          })}

        {data && <Budget plan={data} budget={draft.budget ?? null} onBudget={(budget) => update({ budget })} />}
      </div>

      <div className={`${styles.column} ${styles.sticky}`}>
        {data && previewChoice && draft.cell_profile_id != null && (
          <PreviewPanel
            part={data.part}
            cellProfileId={draft.cell_profile_id}
            gripHeight={draft.grasp?.grip_height_mm ?? null}
            choice={previewChoice}
            param={previewParam}
            params={previewParams}
          />
        )}
      </div>
    </div>
  );
}

function ParamRow({
  param,
  choice,
  appliesTo,
  closedGap,
  onChange,
  onFocus,
}: {
  param: Param;
  choice: FamilyChoice;
  appliesTo?: string;
  closedGap?: string;
  onChange: (edit: (choice: FamilyChoice) => FamilyChoice) => void;
  onFocus: (focused: boolean) => void;
}) {
  const range = choice.ranges[param.name];
  const value: [number, number] = range ? [range.lo, range.hi] : [param.default_range[0], param.default_range[1]];
  const locked = choice.locks[param.name] ?? null;
  const format = (v: number) => paramValue(v, param.unit);

  return (
    <div className={styles.param}>
      <RangeSlider
        label={paramLabel(param.name)}
        min={param.limits[0]}
        max={param.limits[1]}
        format={format}
        value={value}
        locked={locked}
        disabled={!param.applies}
        onFocusChange={onFocus}
        onChange={([lo, hi]) => onChange((c) => ({ ...c, ranges: { ...c.ranges, [param.name]: { lo, hi } } }))}
        onLockChange={(fixed) =>
          onChange((c) => {
            const locks = { ...c.locks };
            if (fixed == null) delete locks[param.name];
            else locks[param.name] = fixed;
            return { ...c, locks };
          })
        }
        hint={
          param.applies
            ? capitalise(param.description) + "."
            : `Doesn't apply to this part${appliesTo ? `: it matters for ${appliesTo} only` : ""}.`
        }
      />
      {closedGap && param.applies && <p className={styles.closedGap}>{closedGap}</p>}
      {param.note && <p className={styles.note}>{capitalise(param.note)}.</p>}
    </div>
  );
}

/** The designs-per-search field, and what the plan makes of it: each search's method, budget and batch, and the time. */
function Budget({ plan, budget, onBudget }: { plan: Plan; budget: number | null; onBudget: (budget: number | null) => void }) {
  const { estimate, totals } = plan;
  return (
    <div className={styles.panel}>
      <h3 className={styles.panelTitle}>Budget</h3>
      <NumberInput
        label="Designs per search"
        unit="designs"
        min={1}
        step={1}
        value={budget}
        onChange={(value) => onBudget(value == null ? null : Math.max(1, Math.round(value)))}
        placeholder="Default"
        hint="Empty: 128 for a Bayesian search, 16 or 32 for a sweep. More free parameters need more designs."
      />
      <Table<Search>
        label="Searches the plan makes"
        rows={plan.searches}
        rowKey={(s) => s.key}
        columns={[
          { key: "family", header: "Search", render: (s) => plan.families.find((f) => f.family === s.family)?.label ?? s.family },
          { key: "method", header: "Method", render: (s) => searchMethodLabel(s.method) },
          { key: "free", header: "Free", align: "right", render: (s) => s.free.length },
          { key: "budget", header: "Designs", align: "right", render: (s) => s.budget },
          { key: "batch", header: "Per round", align: "right", render: (s) => s.batch_size },
        ]}
      />
      <p className={styles.note}>
        {totals.search_designs} designs in {totals.rounds} rounds, {totals.total_grasps.toLocaleString()} grasps in all.{" "}
        {estimate.seconds == null
          ? "The run time is unknown until runs on this sim have measured it."
          : `About ${duration(estimate.seconds)} on this sim (${estimate.source === "measured" ? "measured" : "as configured"}).`}
      </p>
    </div>
  );
}

/** The finger at the focused parameter's lowest and highest values, the others mid-range, as two ghosts on the part. */
function PreviewPanel({
  part,
  cellProfileId,
  gripHeight,
  choice,
  param,
  params,
}: {
  part: Part;
  cellProfileId: number;
  gripHeight: number | null;
  choice: FamilyChoice;
  param: Param | undefined;
  params: Param[];
}) {
  const applicable = params.filter((p) => p.applies);
  const single = applicable.length > 0 && applicable.every((p) => choice.locks[p.name] != null);
  const vary = param && param.applies && choice.locks[param.name] == null ? param.name : null;
  const request = useDebounced({ part, cell_profile_id: cellProfileId, choice, grip_height_mm: gripHeight, vary, single }, 300);
  const preview = useQuery({
    queryKey: ["finger-preview", request],
    queryFn: () => {
      const { single: one, vary: name, ...body } = request;
      return unwrapAs<Preview>(
        api.POST("/api/fingers/preview", {
          body: one ? { ...body, designs: [{ kind: "locked", params: lockedParams(body.choice) }] } : { ...body, vary: name },
        }),
      );
    },
    enabled: request.single || request.vary !== null,
    placeholderData: (previous) => previous,
  });

  const fingers: FingerShape[] = useMemo(
    () =>
      (preview.data?.designs ?? []).flatMap((d, i) =>
        d.finger
          ? [{ key: d.label, pieces: d.finger.pieces, tone: single ? "finger" : i === 0 ? "min" : "max", mirrored: true } as FingerShape]
          : [],
      ),
    [preview.data, single],
  );

  const name = param ? paramLabel(param.name).toLowerCase() : "";
  return (
    <div className={styles.panel}>
      <h3 className={styles.panelTitle}>{single ? "The one design" : vary ? `Preview: ${name}` : "Preview"}</h3>
      {!single && !vary && (
        <p className={styles.note}>Focus a parameter's slider that isn't locked to see the finger at both ends of its range.</p>
      )}
      <FingerViewer
        part={part}
        fingers={fingers}
        label={single ? "The one finger design, on the part" : `The finger at the lowest and highest ${name}, on the part`}
        height={320}
        frameKey={JSON.stringify(part)}
      />
      {preview.isError && <p className={styles.error}>{preview.error.message}</p>}
      {preview.data && (
        <div className={styles.stack}>
          {preview.data.designs.map((d, i) => {
            const at = vary ? d.design.params?.[vary as keyof NonNullable<typeof d.design.params>] : undefined;
            return (
              <div key={d.label} className={styles.stack}>
                <span className={styles.legend}>
                  <span>
                    <span
                      className={`${styles.swatch} ${single ? styles.swatchFinger : i === 0 ? styles.swatchMin : styles.swatchMax}`}
                      aria-hidden="true"
                    />
                    {single ? "This design" : i === 0 ? "Lowest" : "Highest"}
                    {typeof at === "number" && param ? `, ${paramValue(at, param.unit)}` : ""}
                  </span>
                  {d.finger?.closed_gap_mm != null && <span>pads stop {mm(d.finger.closed_gap_mm)} apart fully closed</span>}
                </span>
                {d.problems.map((p) => (
                  <span key={p} className={styles.error}>
                    {capitalise(p)}.
                  </span>
                ))}
              </div>
            );
          })}
          {!single && <p className={styles.note}>The other parameters sit mid-range.</p>}
        </div>
      )}
    </div>
  );
}

/** "With the jaws fully closed, the pads stop 0.4 to 3.6 mm apart": the closed gap the slack sets, at both ends of its
 *  range. Closed gap = part width + 2 x slack - 2 x stroke per jaw (the jaws always open fully before closing). */
function closedGapText(choice: FamilyChoice, param: Param, part: Part, strokePerJaw: number): string {
  const width = widthAcrossJaws(part);
  const gap = (slack: number) => width + 2 * slack - 2 * strokePerJaw;
  const locked = choice.locks[param.name];
  if (locked != null) return `With the jaws fully closed, the pads stop ${mm(gap(locked))} apart.`;
  const range = choice.ranges[param.name];
  const [lo, hi] = range ? [range.lo, range.hi] : param.default_range;
  return `With the jaws fully closed, the pads stop ${mm(gap(lo))} to ${mm(gap(hi))} apart.`;
}

/** The part's size along the jaws' closing direction (x in the grasp frame). */
function widthAcrossJaws(part: Part): number {
  if (part.shape === "box") return part.width_mm;
  if (part.shape === "mesh") {
    const xs = (part.pieces ?? []).flatMap((piece) => piece.points.map((p) => p[0]));
    return xs.length ? Math.max(...xs) - Math.min(...xs) : 0;
  }
  return part.axis === "x" ? part.length_mm : part.diameter_mm;
}

/** A fully locked choice as one design's parameters. */
function lockedParams(choice: FamilyChoice): Schemas["VPadParams"] {
  return { family: "vpad", ...(choice.locks as Omit<Schemas["VPadParams"], "family">) };
}

/** Which parts a parameter applies to, from the family's schema, e.g. "upright cylinders". */
function appliesTo(schema: Record<string, unknown> | null | undefined, name: string): string | undefined {
  const properties = (schema?.properties ?? {}) as Record<string, { applies_to?: string }>;
  return properties[name]?.applies_to;
}

function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}
