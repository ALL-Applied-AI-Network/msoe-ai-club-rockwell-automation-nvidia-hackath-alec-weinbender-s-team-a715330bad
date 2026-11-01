import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, unwrapAs, type Schemas } from "../../../backend/client";
import { meshUrl, usePart } from "../../../backend/queries";
import { Badge } from "../../../components/Badge";
import { Banner } from "../../../components/Banner";
import { Button, LinkButton } from "../../../components/Button";
import { Checkbox, NumberInput } from "../../../components/Field";
import { KeyValues } from "../../../components/KeyValues";
import { PartViewer, type GraspArrow, type PartPick } from "../../../components/PartViewer";
import { RadioCards } from "../../../components/RadioCards";
import { Segmented } from "../../../components/Segmented";
import { ErrorState, Skeleton } from "../../../components/States";
import { degrees, mm, percent, quantity } from "../../../format";
import { useDraft, useStepGate, type DraftPose, type Gate, type PoseChoice } from "../draft";
import { capitalise, findPose, usePoses, weightOf } from "../poses";
import { useDebounced } from "./useDebounced";
import styles from "./designSteps.module.css";

type Proposals = Schemas["GraspProposals"];
type Candidate = Schemas["GraspCandidate"];
type Check = Schemas["CheckGraspResponse"];
type Choice = Schemas["GraspChoice"];
type Pick = Schemas["GraspPick"];

const STEP = 5;

/** Step 5: which way the jaws close on the part, for each pose ticked in step 2 (frontend-plan.md, step 5). Every pose's
 *  chooser stays mounted, so each proposes and checks its own grasp; the tabs show one at a time. */
export function GraspStep() {
  const { draft } = useDraft();
  const part = usePart(draft.part_id);
  const poses = usePoses(draft.part_id);
  const ticked = draft.poses ?? [];
  const [active, setActive] = useState<string | null>(null);
  const [gates, setGates] = useState<Record<string, Gate>>({});
  const onGate = useCallback(
    (key: string, gate: Gate) =>
      setGates((current) => (current[key]?.ok === gate.ok && current[key]?.reason === gate.reason ? current : { ...current, [key]: gate })),
    [],
  );

  const labelOf = (d: DraftPose) => capitalise(findPose(poses.data, d.pose)?.label ?? "pose");
  const failing = ticked.find((d) => !gates[String(d.pose)]?.ok);
  const gate: Gate =
    ticked.length === 0
      ? { ok: false, reason: "Tick a resting pose in step 2 first" }
      : failing
        ? { ok: false, reason: (ticked.length > 1 ? `${labelOf(failing)}: ` : "") + (gates[String(failing.pose)]?.reason ?? "Choose a closing direction") }
        : { ok: true };
  useStepGate(STEP, gate);

  if (!draft.part_id || draft.cell_profile_id == null) {
    return <Banner tone="warn">Choose the part (step 1) and the cell (step 4) first.</Banner>;
  }
  if (part.isPending || poses.isPending) return <Skeleton height={360} />;
  if (part.isError) return <ErrorState title="Couldn't load the part" message={part.error.message} onRetry={() => void part.refetch()} />;
  if (ticked.length === 0) {
    return (
      <Banner tone="warn" action={<LinkButton to="/new/pose">Choose the resting poses</LinkButton>}>
        The grasp depends on how the part sits on the table: tick its resting poses in step 2 first.
      </Banner>
    );
  }

  const shown = ticked.find((d) => String(d.pose) === active) ?? ticked[0];
  const missing = ticked.filter((d) => !gates[String(d.pose)]?.ok);

  return (
    <div className={styles.stack}>
      {ticked.length > 1 && (
        <div className={styles.row}>
          <Segmented
            label="Resting pose"
            value={String(shown.pose)}
            onChange={setActive}
            options={ticked.map((d) => ({
              value: String(d.pose),
              label: `${labelOf(d)}, ${percent(weightOf(d.pose, ticked, poses.data ?? []))}`,
            }))}
          />
          {missing.length > 0 && <span className={styles.note}>Needs a grasp: {missing.map((d) => labelOf(d).toLowerCase()).join(", ")}.</span>}
        </div>
      )}
      {ticked.map((d) => (
        <PoseGrasp
          key={String(d.pose)}
          partId={part.data.id}
          partName={part.data.name}
          pose={d.pose}
          poseLabel={findPose(poses.data, d.pose)?.label ?? "pose"}
          grasp={d.grasp}
          active={d.pose === shown.pose}
          onGate={onGate}
        />
      ))}
    </div>
  );
}

type PoseGraspProps = {
  partId: string;
  partName: string;
  pose: PoseChoice;
  poseLabel: string;
  grasp: Choice | undefined;
  active: boolean; // the shown tab; the others keep running but draw nothing
  onGate: (key: string, gate: Gate) => void;
};

/** One pose's grasp: the proposals for the part in that pose, or two faces picked on it. */
function PoseGrasp({ partId, partName, pose, poseLabel, grasp, active, onGate }: PoseGraspProps) {
  const { draft, setPoseGrasp } = useDraft();
  const profileId = draft.cell_profile_id;
  const ready = profileId != null;
  const update = useCallback((next: Choice) => setPoseGrasp(pose, next), [setPoseGrasp, pose]);

  const proposals = useQuery({
    queryKey: ["grasps", partId, profileId, pose],
    queryFn: () =>
      unwrapAs<Proposals>(
        api.POST("/api/parts/{part_id}/grasps", {
          params: { path: { part_id: partId } },
          body: { cell_profile_id: profileId!, pose },
        }),
      ),
    enabled: ready,
  });

  const [manual, setManual] = useState(grasp?.source === "manual");
  const [angle, setAngle] = useState<number | null>(grasp?.source === "manual" ? grasp.angle_deg : null);
  const [picks, setPicks] = useState<Pick[]>(grasp?.picks ?? []);
  const [fixHeight, setFixHeight] = useState(grasp?.grip_height_mm != null);
  const [height, setHeight] = useState<number | null>(grasp?.grip_height_mm ?? null);
  const gripHeight = fixHeight ? height : null;

  const candidates = proposals.data?.candidates ?? [];
  const chosen = manual ? -1 : candidates.findIndex((c) => grasp?.source === "auto" && sameDirection(c, grasp));

  // An automatic choice follows the proposals: the first by default, or again the first when the pose changed under it.
  useEffect(() => {
    if (manual || candidates.length === 0 || chosen >= 0) return;
    update(autoChoice(candidates[0], gripHeight));
  }, [manual, candidates, chosen, gripHeight, update]);

  // The grip height lock applies to an automatic choice directly; a manual one goes through the check below.
  useEffect(() => {
    if (manual || !grasp || grasp.source !== "auto" || grasp.grip_height_mm === gripHeight) return;
    update({ ...grasp, grip_height_mm: gripHeight });
  }, [manual, grasp, gripHeight, update]);

  const request = useDebounced(
    manual && profileId != null && (picks.length > 0 || angle != null)
      ? { cell_profile_id: profileId, pose, angle_deg: picks.length > 0 ? null : angle, picks, grip_height_mm: gripHeight }
      : null,
    250,
  );
  const check = useQuery({
    queryKey: ["grasp-check", partId, request],
    queryFn: () =>
      unwrapAs<Check>(api.POST("/api/parts/{part_id}/grasps/check", { params: { path: { part_id: partId } }, body: request! })),
    enabled: request !== null && ready,
  });

  // A manual choice that isn't blocked goes into the spec as the check returned it.
  useEffect(() => {
    if (!manual || !check.data || check.data.verdict === "blocked") return;
    if (JSON.stringify(check.data.choice) !== JSON.stringify(grasp)) update(check.data.choice);
  }, [manual, check.data, grasp, update]);

  const nothingFits = proposals.data?.nothing_fits;
  const gate = gateFor({ ready, nothingFits: nothingFits?.reason, manual, picked: picks.length > 0 || angle != null, check: check.data, grasp });
  const { ok, reason } = gate;
  useEffect(() => onGate(String(pose), { ok, reason }), [onGate, pose, ok, reason]);

  const arrows: GraspArrow[] = useMemo(() => {
    if (manual) return check.data ? [{ angle_deg: check.data.angle_deg, centre_mm: check.data.centre_mm, tone: "active" }] : [];
    return candidates.map((c, i) => ({ angle_deg: c.angle_deg, centre_mm: c.centre_mm, tone: i === chosen ? "acc" : "faint" }));
  }, [manual, check.data, candidates, chosen]);

  if (!active) return null;

  const onPick = (p: PartPick) => {
    setManual(true);
    setPicks((current) => (current.length >= 2 ? [p] : [...current, p]));
  };
  const shown: Candidate | Check | undefined = manual ? check.data : candidates[chosen];

  return (
    <div className={styles.split}>
      <div className={styles.column}>
        <PartViewer
          url={meshUrl(partId, pose)}
          label={`${partName}, ${poseLabel}, with the proposed closing directions drawn over it`}
          height={380}
          arrows={arrows}
          markers={manual ? picks : []}
          onPick={onPick}
        />
        <p className={styles.note}>
          Green is the chosen direction, grey the other proposals{manual ? ", blue your own" : ""}. Click two opposite
          faces to choose your own.
        </p>
      </div>

      <div className={styles.column}>
        {proposals.isPending && <Skeleton height={200} />}
        {proposals.isError && (
          <ErrorState title="Couldn't propose a grasp" message={proposals.error.message} onRetry={() => void proposals.refetch()} />
        )}
        {nothingFits && (
          <Banner tone="bad" title="Nothing fits these jaws.">
            <span className={styles.stack}>
              <span>{nothingFits.reason}.</span>
              {nothingFits.suggestions.length > 0 && (
                <span>
                  What could work, best first:
                  <ol className={styles.list}>
                    {nothingFits.suggestions.map((s) => (
                      <li key={s}>{s}</li>
                    ))}
                  </ol>
                </span>
              )}
            </span>
          </Banner>
        )}

        {proposals.data && !nothingFits && (
          <RadioCards
            label="Closing direction"
            columns={1}
            value={manual ? "manual" : chosen >= 0 ? String(chosen) : undefined}
            onChange={(value) => {
              if (value === "manual") {
                setManual(true);
                return;
              }
              setManual(false);
              update(autoChoice(candidates[Number(value)], gripHeight));
            }}
            options={[
              ...candidates.map((c, i) => ({
                value: String(i),
                label: `Close along ${degrees(c.angle_deg, Number.isInteger(c.angle_deg) ? 0 : 1)}`,
                description: c.note ?? describeCandidate(c),
                aside:
                  i === 0 ? <Badge tone="ok" label="Proposed" /> : c.verdict === "warn" ? <Badge tone="warn" label="Warnings" /> : undefined,
              })),
              { value: "manual", label: "Choose it yourself", description: "Click two opposite faces on the 3D view, or type an angle." },
            ]}
          />
        )}

        {manual && (
          <div className={styles.panel}>
            <NumberInput
              label="Closing angle"
              unit="°"
              value={picks.length > 0 ? (check.data?.angle_deg ?? null) : angle}
              onChange={(value) => {
                setPicks([]);
                setAngle(value);
              }}
              hint="From the part's +x axis."
            />
            <div className={styles.row}>
              <span className={styles.note}>
                {picks.length === 0 ? "No faces picked." : picks.length === 1 ? "One face picked: pick the opposite one." : "Two faces picked."}
              </span>
              {picks.length > 0 && (
                <Button variant="ghost" size="sm" onClick={() => setPicks([])}>
                  Clear the picks
                </Button>
              )}
            </div>
            {check.isError && <p className={styles.error}>{check.error.message}</p>}
            {check.data?.verdict === "blocked" && (
              <Banner tone="bad" title="This direction can't work.">
                {check.data.blocked_reasons.join(" ")}
              </Banner>
            )}
          </div>
        )}

        {shown && <GraspFacts grasp={shown} />}

        <div className={styles.panel}>
          <Checkbox
            label="Fix the grip height"
            checked={fixHeight}
            onChange={setFixHeight}
            hint="Otherwise the search chooses it."
          />
          {fixHeight && (
            <NumberInput label="Grip height" unit="mm" value={height} onChange={setHeight} min={2.5} hint="Above the table: at least 2.5 mm." />
          )}
        </div>

        {proposals.data && proposals.data.rejected.length > 0 && (
          <div className={styles.note}>
            Other directions don't work:
            <ul className={styles.list}>
              {proposals.data.rejected.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}

/** The chosen direction's numbers and warnings. */
function GraspFacts({ grasp }: { grasp: Candidate | Check }) {
  return (
    <div className={styles.panel}>
      <KeyValues
        items={[
          { label: "Across the jaws", value: mm(grasp.width_mm) },
          { label: "Along the jaws", value: mm(grasp.depth_mm) },
          { label: "Contact area", value: quantity(Math.round(grasp.contact_area_mm2), "mm²") },
          { label: "Faces", value: grasp.parallel_faces ? "parallel" : `${degrees(grasp.opposition_deg, 1)} off opposite` },
          { label: "Centre of mass", value: `${mm(grasp.com_offset_mm)} off the grasp` },
          { label: "Stock fingers", value: grasp.stock_fits ? "fit" : "don't fit" },
        ]}
      />
      {grasp.warnings.length > 0 && (
        <Banner tone="warn">
          <span className={styles.stack}>
            {grasp.warnings.map((w) => (
              <span key={w}>{capitalise(w)}.</span>
            ))}
          </span>
        </Banner>
      )}
    </div>
  );
}

function gateFor({
  ready,
  nothingFits,
  manual,
  picked,
  check,
  grasp,
}: {
  ready: boolean;
  nothingFits?: string;
  manual: boolean;
  picked: boolean;
  check?: Check;
  grasp?: Choice;
}): Gate {
  if (!ready) return { ok: false, reason: "Choose the cell first" };
  if (nothingFits) return { ok: false, reason: `Nothing fits these jaws: ${nothingFits}` };
  if (manual && !picked) return { ok: false, reason: "Pick two faces on the part, or type an angle" };
  if (manual && check?.verdict === "blocked") return { ok: false, reason: check.blocked_reasons.join(" ") };
  if (!grasp) return { ok: false, reason: "Choose a closing direction" };
  return { ok: true };
}

function autoChoice(candidate: Candidate, gripHeight: number | null): Choice {
  return {
    angle_deg: candidate.angle_deg,
    centre_mm: candidate.centre_mm,
    span_mm: candidate.span_mm ?? null,
    source: "auto",
    grip_height_mm: gripHeight,
    picks: [],
  };
}

/** A section grasp (a screw's shank beside its head) says how wide the pads can be without reaching the wider part. */
function describeCandidate(candidate: Candidate): string {
  if (!candidate.span_mm) return `The jaws close across ${mm(candidate.width_mm)} of the part.`;
  const [near, far] = candidate.span_mm;
  return `Grips a ${mm(candidate.width_mm)} section; pads up to ${mm(2 * Math.min(-near, far))} wide.`;
}

function sameDirection(candidate: Candidate, grasp: Choice | null | undefined): boolean {
  if (!grasp) return false;
  return (
    Math.abs(candidate.angle_deg - grasp.angle_deg) < 0.01 &&
    Math.hypot(candidate.centre_mm[0] - grasp.centre_mm[0], candidate.centre_mm[1] - grasp.centre_mm[1]) < 0.01
  );
}
