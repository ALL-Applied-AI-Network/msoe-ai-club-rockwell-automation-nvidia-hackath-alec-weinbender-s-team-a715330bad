import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { api, unwrap, type Schemas } from "../../backend/client";
import { Button } from "../../components/Button";
import { CopyButton } from "../../components/CopyButton";
import { TextInput } from "../../components/Field";
import { Icon } from "../../components/Icon";
import { Modal } from "../../components/Modal";
import { Segmented } from "../../components/Segmented";
import { Select } from "../../components/Select";
import { EmptyState } from "../../components/States";
import { designLabel } from "../../labels";
import { useRefreshJob } from "./queries";
import { Stage } from "./Stage";
import styles from "./JobValidationPage.module.css";

type PrintedFinger = Schemas["PrintedFinger"];
type Side = PrintedFinger["side"];

const SIDES: { value: Side; label: string }[] = [
  { value: "pair", label: "Pair" },
  { value: "L", label: "Left" },
  { value: "R", label: "Right" },
];

/** Stage 2: record each finger as it comes off the printer. The app gives it the ID to engrave on it. */
export function PrintedFingersStage({
  jobId,
  toPrint,
  printable,
  fingers,
}: {
  jobId: string;
  toPrint: string[]; // the print selection plus the imprint: what this stage is waiting for
  printable: string[]; // every design that can be printed (not STOCK)
  fingers: PrintedFinger[];
}) {
  const [adding, setAdding] = useState(false);
  const printed = new Set(fingers.map((f) => f.design_label));
  const done = toPrint.filter((label) => printed.has(label)).length;
  const missing = toPrint.filter((label) => !printed.has(label));

  return (
    <Stage
      step={2}
      title="Record the printed fingers"
      status={
        toPrint.length > 0 && done === toPrint.length
          ? { tone: "ok", label: "All printed" }
          : { tone: done ? "active" : "neutral", label: `${done} of ${toPrint.length} printed` }
      }
      description="Record each finger once it's printed. Engrave the ID the app gives it on the finger: logged trials refer to it."
    >
      {missing.length > 0 && (
        <p className={styles.note}>Still to print: {missing.map(designLabel).join(", ")}.</p>
      )}
      {fingers.length === 0 ? (
        <EmptyState
          title="No printed fingers yet"
          action={
            <Button onClick={() => setAdding(true)}>
              <Icon name="plus" />
              Record a printed finger
            </Button>
          }
        >
          Print the chosen designs and the imprint, then record each one here to get its ID.
        </EmptyState>
      ) : (
        <>
          <ul className={styles.fingers}>
            {[...fingers].reverse().map((finger) => (
              <li key={finger.id} className={styles.finger}>
                <div className={styles.fingerId}>{finger.finger_id}</div>
                <div className={styles.fingerMeta}>
                  {designLabel(finger.design_label)}, {SIDES.find((s) => s.value === finger.side)?.label.toLowerCase()},{" "}
                  {finger.material}
                  {finger.print_date ? `, printed ${finger.print_date}` : ""}
                </div>
                {finger.notes && <div className={styles.fingerNotes}>{finger.notes}</div>}
                <CopyButton text={finger.finger_id} label="Copy the ID" />
              </li>
            ))}
          </ul>
          <div>
            <Button variant="secondary" onClick={() => setAdding(true)}>
              <Icon name="plus" />
              Record a printed finger
            </Button>
          </div>
        </>
      )}
      <AddFingerModal
        open={adding}
        jobId={jobId}
        printable={printable}
        suggested={missing[0] ?? printable[0] ?? ""}
        onClose={() => setAdding(false)}
      />
    </Stage>
  );
}

function AddFingerModal({
  open,
  jobId,
  printable,
  suggested,
  onClose,
}: {
  open: boolean;
  jobId: string;
  printable: string[];
  suggested: string;
  onClose: () => void;
}) {
  const refresh = useRefreshJob(jobId);
  const [design, setDesign] = useState("");
  const [side, setSide] = useState<Side>("pair");
  const [material, setMaterial] = useState("PLA");
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [notes, setNotes] = useState("");
  const add = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/jobs/{job_id}/printed-fingers", {
          params: { path: { job_id: jobId } },
          body: { design_label: design || suggested, side, material, print_date: date || null, notes },
        }),
      ),
    onSuccess: () => {
      setNotes("");
      onClose();
    },
    onSettled: refresh,
  });

  return (
    <Modal
      open={open}
      title="Record a printed finger"
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={add.isPending}>
            Cancel
          </Button>
          <Button onClick={() => add.mutate()} disabled={add.isPending || !material.trim()}>
            Record it and get its ID
          </Button>
        </>
      }
    >
      <Select
        label="Design"
        value={design || suggested}
        onChange={(event) => setDesign(event.target.value)}
        options={printable.map((label) => ({ value: label, label: designLabel(label) }))}
      />
      <div className={styles.fieldGroup}>
        <span className={styles.fieldLabel}>Side</span>
        <Segmented label="Side" value={side} onChange={setSide} options={SIDES} />
      </div>
      <TextInput
        label="Material"
        value={material}
        onChange={setMaterial}
        hint="It should match the pad friction the sim assumed."
      />
      <TextInput label="Print date" type="date" value={date} onChange={setDate} />
      <TextInput label="Notes" value={notes} onChange={setNotes} placeholder="Optional, e.g. the printer and its settings" />
      {add.error && <p className={styles.error}>{add.error.message}</p>}
    </Modal>
  );
}
