import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { api, unwrapAs, type Schemas } from "../../../backend/client";
import { meshUrl, usePart } from "../../../backend/queries";
import { Badge } from "../../../components/Badge";
import { Banner } from "../../../components/Banner";
import { Button, LinkButton } from "../../../components/Button";
import { Checkbox, NumberInput } from "../../../components/Field";
import { KeyValues } from "../../../components/KeyValues";
import { PartViewer, type GraspArrow, type PartPick } from "../../../components/PartViewer";
import { RadioCards } from "../../../components/RadioCards";
import { ErrorState, Skeleton } from "../../../components/States";
import { degrees, mm, quantity } from "../../../format";
import { useDraft, useStepGate } from "../draft";
import { useDebounced } from "./useDebounced";
import styles from "./designSteps.module.css";

type Proposals = Schemas["GraspProposals"];
type Candidate = Schemas["GraspCandidate"];
type Check = Schemas["CheckGraspResponse"];
type Choice = Schemas["GraspChoice"];
type Pick = Schemas["GraspPick"];

const STEP = 5;

/** Step 5: which way the jaws close on the part (frontend-plan.md, step 5). The app proposes the best directions for the
 *  pose and the cell's stroke; the first is chosen unless the user picks another, or picks two faces on the part. */
export function GraspStep() {
  const { draft, update } = useDraft();
  const part = usePart(draft.part_id);
  const profileId = draft.cell_profile_id;
  const pose = part.data?.pose;
  const ready = Boolean(draft.part_id) && profileId != null && Boolean(pose);

  const proposals = useQuery({
    queryKey: ["grasps", draft.part_id, profileId, pose?.label, pose?.rotation],
    queryFn: () =>
      unwrapAs<Proposals>(
        api.POST("/api/parts/{part_id}/grasps", {
          params: { path: { part_id: draft.part_id! } },
          body: { cell_profile_id: profileId! },
        }),
      ),
    enabled: ready,
  });

  const [manual, setManual] = useState(draft.grasp?.source === "manual");
  const [angle, setAngle] = useState<number | null>(draft.grasp?.source === "manual" ? draft.grasp.angle_deg : null);
  const [picks, setPicks] = useState<Pick[]>(draft.grasp?.picks ?? []);
  const [fixHeight, setFixHeight] = useState(draft.grasp?.grip_height_mm != null);
  const [height, setHeight] = useState<number | null>(draft.grasp?.grip_height_mm ?? null);
  const gripHeight = fixHeight ? height : null;

  const candidates = proposals.data?.candidates ?? [];
  const chosen = manual ? -1 : candidates.findIndex((c) => draft.grasp?.source === "auto" && sameDirection(c, draft.grasp));

  // An automatic choice follows the proposals: the first by default, or again the first when the pose changed under it.
  useEffect(() => {
    if (manual || candidates.length === 0 || chosen >= 0) return;
    update({ grasp: autoChoice(candidates[0], gripHeight) });
  }, [manual, candidates, chosen, gripHeight, update]);

  // The grip height lock applies to an automatic choice directly; a manual one goes through the check below.
  useEffect(() => {
    if (manual || !draft.grasp || draft.grasp.source !== "auto" || draft.grasp.grip_height_mm === gripHeight) return;
    update({ grasp: { ...draft.grasp, grip_height_mm: gripHeight } });
  }, [manual, draft.grasp, gripHeight, update]);

  const request = useDebounced(
    manual && profileId != null && (picks.length > 0 || angle != null)
      ? { cell_profile_id: profileId, angle_deg: picks.length > 0 ? null : angle, picks, grip_height_mm: gripHeight }
      : null,
    250,
  );
  const check = useQuery({
    queryKey: ["grasp-check", draft.part_id, request],
    queryFn: () =>
      unwrapAs<Check>(
        api.POST("/api/parts/{part_id}/grasps/check", { params: { path: { part_id: draft.part_id! } }, body: request! }),
      ),
    enabled: request !== null && ready,
  });

  // A manual choice that isn't blocked goes into the spec as the check returned it.
  useEffect(() => {
    if (!manual || !check.data || check.data.verdict === "blocked") return;
    if (JSON.stringify(check.data.choice) !== JSON.stringify(draft.grasp)) update({ grasp: check.data.choice });
  }, [manual, check.data, draft.grasp, update]);

  const nothingFits = proposals.data?.nothing_fits;
  const gate = gateFor({ ready, nothingFits: nothingFits?.reason, manual, picked: picks.length > 0 || angle != null, check: check.data, grasp: draft.grasp });
  useStepGate(STEP, gate);

  const arrows: GraspArrow[] = useMemo(() => {
    if (manual) return check.data ? [{ angle_deg: check.data.angle_deg, centre_mm: check.data.centre_mm, tone: "active" }] : [];
    return candidates.map((c, i) => ({ angle_deg: c.angle_deg, centre_mm: c.centre_mm, tone: i === chosen ? "acc" : "faint" }));
  }, [manual, check.data, candidates, chosen]);

  if (!draft.part_id || profileId == null) {
    return <Banner tone="warn">Choose the part (step 1) and the cell profile (step 4) first.</Banner>;
  }
  if (part.isPending) return <Skeleton height={360} />;
  if (part.isError) return <ErrorState title="Couldn't load the part" message={part.error.message} onRetry={() => void part.refetch()} />;
  if (!pose) {
    return (
      <Banner tone="warn" action={<LinkButton to="/new/pose">Choose a resting pose</LinkButton>}>
        The grasp depends on how the part sits on the table: choose its resting pose in step 2 first.
      </Banner>
    );
  }

  const onPick = (p: PartPick) => {
    setManual(true);
    setPicks((current) => (current.length >= 2 ? [p] : [...current, p]));
  };
  const shown: Candidate | Check | undefined = manual ? check.data : candidates[chosen];

  return (
    <div className={styles.split}>
      <div className={styles.column}>
        <PartViewer
          url={meshUrl(part.data.id)}
          label={`${part.data.name}, ${pose.label}, with the proposed closing directions drawn over it`}
          height={380}
          arrows={arrows}
          markers={manual ? picks : []}
          onPick={onPick}
        />
        <p className={styles.note}>
          Arrows show the jaws closing on the part: green is the chosen direction, grey the other proposals
          {manual ? ", blue your own choice" : ""}. Click two opposite faces to choose a direction yourself.
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
              update({ grasp: autoChoice(candidates[Number(value)], gripHeight) });
            }}
            options={[
              ...candidates.map((c, i) => ({
                value: String(i),
                label: `Close along ${degrees(c.angle_deg, Number.isInteger(c.angle_deg) ? 0 : 1)}`,
                description: c.note ?? `The jaws close across ${mm(c.width_mm)} of the part.`,
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
              hint="From the part's +x axis, as the 3D view shows it. Picking faces sets it for you."
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
            hint="Left unticked, the search chooses the height the fingers hold the part at."
          />
          {fixHeight && (
            <NumberInput label="Grip height" unit="mm" value={height} onChange={setHeight} min={0} hint="Above the table." />
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
}): { ok: boolean; reason?: string } {
  if (!ready) return { ok: false, reason: "Choose the part, its pose and the cell profile first" };
  if (nothingFits) return { ok: false, reason: `Nothing fits these jaws: ${nothingFits}` };
  if (manual && !picked) return { ok: false, reason: "Pick two faces on the part, or type an angle" };
  if (manual && check?.verdict === "blocked") return { ok: false, reason: check.blocked_reasons.join(" ") };
  if (!grasp) return { ok: false, reason: "Choose a closing direction" };
  return { ok: true };
}

function autoChoice(candidate: Candidate, gripHeight: number | null): Choice {
  return { angle_deg: candidate.angle_deg, centre_mm: candidate.centre_mm, source: "auto", grip_height_mm: gripHeight, picks: [] };
}

function sameDirection(candidate: Candidate, grasp: Choice | undefined): boolean {
  if (!grasp) return false;
  return (
    Math.abs(candidate.angle_deg - grasp.angle_deg) < 0.01 &&
    Math.hypot(candidate.centre_mm[0] - grasp.centre_mm[0], candidate.centre_mm[1] - grasp.centre_mm[1]) < 0.01
  );
}

function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}
