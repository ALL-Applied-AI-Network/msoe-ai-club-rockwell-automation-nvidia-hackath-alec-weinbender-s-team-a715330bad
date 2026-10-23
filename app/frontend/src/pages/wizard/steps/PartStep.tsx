import { useState } from "react";
import { meshUrl, usePart, useParts } from "../../../backend/queries";
import { TextInput } from "../../../components/Field";
import { PartForm } from "../../../components/PartForm";
import { PartUpload } from "../../../components/PartUpload";
import { PartViewer } from "../../../components/PartViewer";
import { Segmented } from "../../../components/Segmented";
import { Stat } from "../../../components/Stat";
import { ErrorState, Skeleton } from "../../../components/States";
import { dims, mass } from "../../../format";
import { useDraft, useStepGate } from "../draft";
import styles from "../Wizard.module.css";

/** Step 1: the experiment's name, and the part: one from the library or a new CAD file. Its size shows large right
 *  away, since that's where a units mistake shows; then its material, mass and handling. */
export function PartStep() {
  const { draft, update } = useDraft();
  const parts = useParts();
  const part = usePart(draft.part_id);
  const [source, setSource] = useState<"library" | "upload">("library");
  useStepGate(1, draft.part_id ? { ok: true } : { ok: false, reason: "Choose a part, or upload one" });

  // Poses and their grasps belong to one part, so a new part clears them.
  const choose = (id: string) => {
    if (id !== draft.part_id) update({ part_id: id, poses: undefined });
  };
  const today = new Date().toISOString().slice(0, 10);
  const stem = part.data ? part.data.name.replace(/\.[^.]+$/, "") : "part";

  return (
    <>
      <TextInput
        label="Experiment name"
        value={draft.name ?? ""}
        onChange={(name) => update({ name: name || null })}
        placeholder={`${stem}_${today}`}
      />

      <div className={styles.section}>
        <div className={styles.sectionHead}>
          <Segmented
            label="Where the part comes from"
            value={source}
            onChange={setSource}
            options={[
              { value: "library", label: "Library", count: parts.data?.length },
              { value: "upload", label: "Upload" },
            ]}
          />
        </div>

        {source === "upload" ? (
          <PartUpload
            onUploaded={(uploaded) => {
              choose(uploaded.id);
              setSource("library");
            }}
          />
        ) : parts.isPending ? (
          <Skeleton height={160} />
        ) : parts.isError ? (
          <ErrorState title="Couldn't load the parts" message={parts.error.message} onRetry={() => parts.refetch()} />
        ) : parts.data.length === 0 ? (
          <p className={styles.note}>No parts yet: upload a STEP or STL file.</p>
        ) : (
          <div className={styles.choiceGrid} role="radiogroup" aria-label="Part">
            {parts.data.map((p) => (
              <button
                key={p.id}
                type="button"
                role="radio"
                aria-checked={p.id === draft.part_id}
                className={styles.choice}
                onClick={() => choose(p.id)}
              >
                <PartViewer url={meshUrl(p.id)} label={p.name} mode="thumbnail" />
                <span className={styles.choiceLabel}>{p.name}</span>
                <span className={styles.choiceNote}>
                  {dims(p.extent_mm)}
                  {p.confirmed_mass_g != null && `, ${mass(p.confirmed_mass_g, p.mass_unit)}`}
                </span>
              </button>
            ))}
          </div>
        )}
      </div>

      {part.data && (
        <>
          <div className={styles.sizeRow}>
            <Stat size="lg" label="Size" value={dims(part.data.extent_mm)} />
            <p className={styles.note}>
              Off by 25.4 times? The file's units were read wrong: upload it again
              {part.data.source === "stl" ? " with the other units" : ""}.
            </p>
          </div>
          <PartForm key={part.data.id} part={part.data} />
        </>
      )}
    </>
  );
}
