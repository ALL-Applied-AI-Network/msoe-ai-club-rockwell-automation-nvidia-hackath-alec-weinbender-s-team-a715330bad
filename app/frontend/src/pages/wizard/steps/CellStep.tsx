import { useState } from "react";
import type { Schemas } from "../../../backend/client";
import { useCellProfile, useCellProfiles } from "../../../backend/queries";
import { Banner } from "../../../components/Banner";
import { Button, LinkButton } from "../../../components/Button";
import { Card } from "../../../components/Card";
import { KeyValues } from "../../../components/KeyValues";
import { Select } from "../../../components/Select";
import { ErrorState, Skeleton } from "../../../components/States";
import { CAVEATS } from "../../../caveats";
import { dateTime, dims, mm, trim } from "../../../format";
import { useDraft, useStepGate } from "../draft";
import styles from "../Wizard.module.css";

type Profile = Schemas["CellProfileResponse"];

/** Step 4: the saved robot, gripper and cell, confirmed at one exact version. It comes before the grasp because which
 *  grasps fit depends on the gripper's stroke. */
export function CellStep() {
  const { draft, update } = useDraft();
  const profiles = useCellProfiles();
  const confirmed = useCellProfile(draft.cell_profile_id);
  const [chosen, setChosen] = useState<number | null>(null);
  useStepGate(4, draft.cell_profile_id != null ? { ok: true } : { ok: false, reason: "Confirm a cell" });

  if (profiles.isPending) return <Skeleton height={320} />;
  if (profiles.isError) return <ErrorState title="Couldn't load the cells" message={profiles.error.message} onRetry={() => profiles.refetch()} />;

  // The profile on show: the one picked in the list, else the confirmed one's latest version, else the first.
  const latestOfConfirmed = confirmed.data && profiles.data.find((p) => p.name === confirmed.data.name);
  const shownId = chosen ?? latestOfConfirmed?.id ?? profiles.data[0]?.id;
  const shown = profiles.data.find((p) => p.id === shownId);
  const isConfirmed = shown != null && shown.id === draft.cell_profile_id;
  const olderVersion = confirmed.data && latestOfConfirmed && latestOfConfirmed.id !== confirmed.data.id ? confirmed.data : null;

  return (
    <>
      <div className={styles.cellPicker}>
        <Select
          label="Cell"
          value={shownId != null ? String(shownId) : ""}
          onChange={(event) => setChosen(Number(event.target.value))}
          options={profiles.data.map((p) => ({ value: String(p.id), label: `${p.name}, version ${p.version}` }))}
        />
        <Button
          disabled={!shown || isConfirmed}
          onClick={() =>
            // the stroke decides which grasps fit, so every pose's grasp is chosen again
            shown && update({ cell_profile_id: shown.id, poses: draft.poses?.map((p) => ({ pose: p.pose })) })
          }
        >
          {isConfirmed ? "Confirmed" : "Confirm this cell"}
        </Button>
      </div>

      {olderVersion && (
        <Banner tone="info">
          The copied experiment ran with version {olderVersion.version} of {olderVersion.name}. Version {latestOfConfirmed?.version} is newer:
          confirm it to use it, or keep version {olderVersion.version}.
        </Banner>
      )}

      {shown && <ProfileCard profile={olderVersion && !chosen ? olderVersion : shown} />}
    </>
  );
}

function ProfileCard({ profile }: { profile: Profile }) {
  const p = profile.profile;
  const placeholder = (field: string) => p.to_confirm.includes(field);
  return (
    <Card
      title={profile.name}
      subtitle={`Version ${profile.version}, saved ${dateTime(profile.created)}`}
      aside={
        <LinkButton variant="secondary" size="sm" to={`/cells/${profile.id}`}>
          Edit in Settings
        </LinkButton>
      }
    >
      {profile.twin_mismatches.length > 0 && (
        <Banner tone="warn" title="Results simulate the twin's gripper">
          {CAVEATS.twinMismatch} {profile.twin_mismatches.join("; ")}.
        </Banner>
      )}
      <KeyValues
        items={[
          { label: "Robot", value: p.robot_model, placeholder: placeholder("robot_model") },
          { label: "Gripper", value: p.gripper_model, placeholder: placeholder("gripper_model") },
          { label: "Stroke per jaw", value: mm(p.stroke_per_jaw_mm), placeholder: placeholder("stroke_per_jaw_mm") },
          { label: "Stock fingers", value: `${p.stock_fingers} (${dims(p.stock_finger_mm, 0)})`, placeholder: placeholder("stock_fingers") },
          {
            label: "Free space beside the gripper",
            value: `${mm(p.free_space_mm[0], 0)} along the jaws, ${mm(p.free_space_mm[1], 0)} across`,
            placeholder: placeholder("free_space_mm"),
          },
          {
            label: "Pad friction",
            value: `${trim(p.pad_friction[0])} static, ${trim(p.pad_friction[1])} sliding (${p.pad_material})`,
            placeholder: placeholder("pad_friction"),
          },
          {
            label: "Finger mount",
            value: `On the jaw's ${p.finger_mount.face} face, ${p.finger_mount.holes.length} holes`,
            placeholder: placeholder("finger_mount"),
          },
        ]}
      />
      {p.to_confirm.length > 0 && <p className={styles.note}>{CAVEATS.placeholderCell} Measure them at the cell, then clear the mark in Settings.</p>}
    </Card>
  );
}
