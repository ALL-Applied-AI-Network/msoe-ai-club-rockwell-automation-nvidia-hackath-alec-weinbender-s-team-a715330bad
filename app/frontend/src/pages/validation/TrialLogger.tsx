import { useEffect, useMemo, useState } from "react";
import type { Schemas } from "../../backend/client";
import { Banner } from "../../components/Banner";
import { Button } from "../../components/Button";
import { TextInput } from "../../components/Field";
import { Segmented } from "../../components/Segmented";
import { EmptyState } from "../../components/States";
import { degrees, mm } from "../../format";
import { designLabel } from "../../labels";
import { useLogTrial } from "./queries";
import styles from "./TrialLogger.module.css";

type Row = Schemas["PlannedTrial"];
type Logged = Schemas["PhysicalTrial"];
type Outcome = Logged["outcome"];

/** Logging a test plan one trial at a time, at the robot on a phone or tablet (docs/notes/frontend-plan.md, 8.4): the
 *  offset to command in large text, then Held, Missed or Skipped, one call each, and on to the next. The sim's
 *  prediction is never shown, so the operator tests blind, as with the spreadsheet. The other way to log is uploading
 *  the filled-in spreadsheet; both are in the validation page's logging stage. */
export function TrialLogger({
  jobId,
  planId,
  rows,
  logged,
  tolerance,
}: {
  jobId: string;
  planId: number;
  rows: Row[];
  logged: Logged[];
  tolerance: boolean; // place and insert: a held part was also within the task's tolerance, or not
}) {
  const log = useLogTrial(jobId);
  const outcomes = useMemo(() => new Map(logged.map((t) => [t.trial_id, t])), [logged]);
  const pending = rows.filter((row) => !outcomes.has(row.trial_id));
  const [cursor, setCursor] = useState<string | undefined>(() => pending[0]?.trial_id);
  const [last, setLast] = useState<{ trialId: string; outcome: Outcome } | null>(null);
  const [inTolerance, setInTolerance] = useState<"yes" | "no" | "">("");
  const [note, setNote] = useState("");

  const index = rows.findIndex((row) => row.trial_id === cursor);
  const row = index >= 0 ? rows[index] : undefined;
  const already = row ? outcomes.get(row.trial_id) : undefined;

  // A fresh trial starts with empty fields.
  useEffect(() => {
    setInTolerance("");
    setNote("");
  }, [cursor]);

  const submit = (outcome: Outcome) => {
    if (!row) return;
    log.mutate(
      {
        trial_id: row.trial_id,
        plan_id: planId,
        outcome,
        in_tolerance: tolerance && outcome === "held" && inTolerance ? inTolerance === "yes" : null,
        notes: note.trim(),
      },
      {
        onSuccess: () => {
          setLast({ trialId: row.trial_id, outcome });
          // On to the next trial still to log, after this one, then from the top.
          const after = rows.slice(index + 1).find((r) => !outcomes.has(r.trial_id) && r.trial_id !== row.trial_id);
          const before = rows.slice(0, index).find((r) => !outcomes.has(r.trial_id));
          setCursor((after ?? before)?.trial_id);
        },
      },
    );
  };

  return (
    <div className={styles.logger}>
      {last && (
        <div className={styles.last}>
          <span>
            Logged {last.trialId} as {last.outcome}.
          </span>
          <Button variant="ghost" size="sm" onClick={() => setCursor(last.trialId)}>
            Change it
          </Button>
        </div>
      )}

      {!row ? (
        <EmptyState title={`Every trial in plan ${planId} is logged`}>The comparison with the sim is below.</EmptyState>
      ) : (
        <section className={styles.trial} aria-label={`Trial ${row.trial_id}`}>
          <div className={styles.trialHead}>
            <span className={styles.trialId}>{row.trial_id}</span>
            <span className={styles.faint}>
              Trial {index + 1} of {rows.length}
            </span>
          </div>
          <div className={styles.design}>
            <span className={styles.designName}>{designLabel(row.design_label)}</span>
            <span className={styles.finger}>
              {row.finger_id ?? (row.design_label === "STOCK" ? "The robot's stock fingers" : "No printed finger recorded")}
            </span>
            <span className={styles.faint}>
              {row.kind === "pointwise" ? `Fixed offset, repeat ${row.repeat}` : "Random offset"}
            </span>
          </div>

          <div className={styles.command}>
            <span className={styles.commandLabel}>Command this offset on the robot</span>
            <div className={styles.offsets}>
              <Axis name="x" value={mm(row.offset_x_mm)} />
              <Axis name="y" value={mm(row.offset_y_mm)} />
              <Axis name="yaw" value={degrees(row.yaw_deg)} />
            </div>
            <span className={styles.faint}>Don't move the part: it stays where it always is.</span>
          </div>

          {already && (
            <Banner tone="info">
              Already logged as {already.outcome}. Logging it again replaces it; the old outcome stays in the history.
            </Banner>
          )}

          {tolerance && (
            <div className={styles.tolerance}>
              <span className={styles.commandLabel}>If held: did the part land within the task's tolerance?</span>
              <Segmented
                label="Within tolerance"
                value={inTolerance}
                onChange={setInTolerance}
                options={[
                  { value: "yes", label: "Within tolerance" },
                  { value: "no", label: "Outside it" },
                  { value: "", label: "Not checked" },
                ]}
              />
            </div>
          )}

          <TextInput label="Note (optional)" value={note} onChange={setNote} placeholder="Anything odd about this grasp" />

          <div className={styles.buttons}>
            <Button className={styles.big} disabled={log.isPending} onClick={() => submit("held")}>
              Held
            </Button>
            <Button className={styles.big} variant="danger" disabled={log.isPending} onClick={() => submit("missed")}>
              Missed
            </Button>
          </div>
          <div className={styles.secondary}>
            <Button variant="ghost" disabled={log.isPending} onClick={() => submit("skipped")}>
              Skipped
            </Button>
            {pending.length > 1 && (
              <Button
                variant="ghost"
                onClick={() => {
                  const next = rows.slice(index + 1).find((r) => !outcomes.has(r.trial_id));
                  setCursor((next ?? pending[0]).trial_id);
                }}
              >
                Do this one later
              </Button>
            )}
          </div>
          {log.error && <p className={styles.error}>{log.error.message}</p>}
        </section>
      )}
    </div>
  );
}

function Axis({ name, value }: { name: string; value: string }) {
  return (
    <div className={styles.axis}>
      <span className={styles.axisName}>{name}</span>
      <span className={styles.axisValue}>{value}</span>
    </div>
  );
}
