import { useState } from "react";
import type { Schemas } from "../../../backend/client";
import { useMeta } from "../../../backend/queries";
import { NumberInput } from "../../../components/Field";
import { RadioCards } from "../../../components/RadioCards";
import { Select } from "../../../components/Select";
import { Table } from "../../../components/Table";
import { VideoPlayer } from "../../../components/VideoPlayer";
import { quantity } from "../../../format";
import { useDraft, useStepGate } from "../draft";
import styles from "../Wizard.module.css";

type Kind = Schemas["Task"]["kind"];

// What each task counts as a success, and which fingers it tends to favour (frontend-plan.md, step 3).
const TASKS: Record<Kind, { success: string; favours: string; video: string }> = {
  drop: {
    success: "Held through the lift (and the transport, if on)",
    favours: "Most slack, widest capture",
    video: "The robot picks a 10 mm cube, lifts it, carries it 10 cm and opens over a bin; the cube falls in.",
  },
  place: {
    success: "Held, and the part sits within the offset tolerance",
    favours: "Centring features: V-groove, lead-in",
    video: "The robot picks a 10 mm cube, lifts it, carries it 10 cm and sets it down on a marked square.",
  },
  insert: {
    success: "Held, within the offset and tilt tolerances",
    favours: "Strong centring, a grip that holds the part's shape",
    video:
      "The robot picks a 10 mm cube, lifts it, carries it 10 cm and lowers it into a square socket 0.75 mm wider than the cube on each side.",
  },
};

// Sensible starting tolerances when a kind first needs them.
const DEFAULT_OFFSET_MM = 1.5;
const DEFAULT_TILT_DEG = 5;

/** Step 3: what happens after the pick, and so what counts as a success. Each kind's example video plays beside the
 *  choices; only the tolerances the kind needs are asked for. */
export function TaskStep() {
  const { draft, update } = useDraft();
  const meta = useMeta();
  const [highlighted, setHighlighted] = useState<Kind | undefined>();
  const task = draft.task ?? { kind: "drop" as const };
  const kinds = meta.data?.task_kinds ?? [];
  const needs = (tolerance: string) => kinds.find((k) => k.name === task.kind)?.tolerances.includes(tolerance) ?? false;
  const needsOffset = needs("offset_tolerance_mm");
  const needsTilt = needs("tilt_tolerance_deg");

  const offsetOk = !needsOffset || (task.offset_tolerance_mm ?? 0) > 0;
  const tiltOk = !needsTilt || (task.tilt_tolerance_deg ?? 0) > 0;
  useStepGate(
    3,
    !offsetOk ? { ok: false, reason: "Set the placement tolerance" } : !tiltOk ? { ok: false, reason: "Set the tilt tolerance" } : { ok: true },
  );

  const setTask = (patch: Partial<Schemas["Task"]>) => update({ task: { ...task, ...patch } });
  const chooseKind = (kind: Kind) => {
    const tolerances = kinds.find((k) => k.name === kind)?.tolerances ?? [];
    setTask({
      kind,
      offset_tolerance_mm: tolerances.includes("offset_tolerance_mm") ? (task.offset_tolerance_mm ?? DEFAULT_OFFSET_MM) : null,
      tilt_tolerance_deg: tolerances.includes("tilt_tolerance_deg") ? (task.tilt_tolerance_deg ?? DEFAULT_TILT_DEG) : null,
    });
  };

  const shown = highlighted ?? task.kind;
  const shownLabel = kinds.find((k) => k.name === shown)?.label ?? shown;

  return (
    <>
      <div className={styles.taskLayout}>
        <div className={styles.taskChoices}>
          <RadioCards
            label="Task"
            columns={1}
            value={task.kind}
            onChange={chooseKind}
            onHighlight={setHighlighted}
            options={kinds.map((k) => ({ value: k.name, label: k.label, description: TASKS[k.name].success }))}
          />
        </div>
        <VideoPlayer
          key={shown}
          src={`/task-examples/${shown}.mp4`}
          poster={`/task-examples/${shown}.jpg`}
          label={`${shownLabel}, in Isaac Sim. ${TASKS[shown].video}`}
          caption={
            <>
              Example in Isaac Sim: the robot's stock fingers and a 10 mm cube. Your part and fingers will differ. The sim
              scores the grasp, the lift, any transport move and how the part sits in the hand, not the drop, place or
              insert themselves: a place or insert counts when the part sits in the hand within the tolerances.
            </>
          }
        />
      </div>

      <Table
        label="What each task counts as a success"
        rowKey={(row) => row.name}
        rows={kinds}
        columns={[
          { key: "task", header: "Task", render: (k) => k.label },
          { key: "success", header: "Counts as success", render: (k) => TASKS[k.name].success },
          { key: "favours", header: "Tends to favour", render: (k) => TASKS[k.name].favours },
        ]}
      />

      <div className={styles.fields}>
        {needsOffset && (
          <NumberInput
            label="Placement tolerance"
            unit="mm"
            min={0}
            step={0.1}
            value={task.offset_tolerance_mm}
            onChange={(value) => setTask({ offset_tolerance_mm: value })}
            error={offsetOk ? undefined : "Needs a tolerance above 0 mm"}
            hint="How far the part may sit off centre in the hand and still count."
          />
        )}
        {needsTilt && (
          <NumberInput
            label="Tilt tolerance"
            unit="°"
            min={0}
            step={0.5}
            value={task.tilt_tolerance_deg}
            onChange={(value) => setTask({ tilt_tolerance_deg: value })}
            error={tiltOk ? undefined : "Needs a tolerance above 0°"}
            hint="How far the part may tilt in the hand and still go in."
          />
        )}
        <Select
          label="Transport move"
          value={task.transport ?? ""}
          onChange={(event) => setTask({ transport: (event.target.value || null) as Schemas["Task"]["transport"] })}
          options={[
            { value: "", label: "None" },
            ...(meta.data?.transports ?? []).map((t) => ({
              value: t.name,
              label: `${t.label}: ${quantity(t.distance_mm, "mm")} in ${quantity(t.move_s, "s")}`,
            })),
          ]}
          hint="Optional. A quick move after the lift, to test how secure the grip is."
        />
      </div>

      <p className={styles.note}>
        The task changes which finger wins, not how the search runs, and it can be changed afterwards on the results page
        without simulating again.
      </p>
    </>
  );
}
