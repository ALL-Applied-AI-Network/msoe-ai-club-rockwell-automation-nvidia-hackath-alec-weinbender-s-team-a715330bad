import { useId, useRef, useState, type ReactNode } from "react";
import styles from "./FileDrop.module.css";

type FileDropProps = {
  label: string; // what to drop, e.g. "Drop a STEP or STL file"
  accept: string; // file extensions, e.g. ".step,.stp,.stl"
  hint?: ReactNode; // shown before anyone tries, e.g. the SolidWorks export hint
  busy?: string; // while uploading: what's happening, e.g. "Reading the part"
  error?: string;
  onFile: (file: File) => void;
};

/** Drop a file here or choose one: the CAD upload and the test-plan spreadsheet upload. */
export function FileDrop({ label, accept, hint, busy, error, onFile }: FileDropProps) {
  const input = useRef<HTMLInputElement>(null);
  const id = useId();
  const [over, setOver] = useState(false);
  const take = (files: FileList | null) => {
    const file = files?.[0];
    if (file && !busy) onFile(file);
  };

  return (
    <div>
      <label
        htmlFor={id}
        className={[styles.zone, over && styles.over, busy && styles.busy, error && styles.invalid].filter(Boolean).join(" ")}
        onDragOver={(event) => {
          event.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(event) => {
          event.preventDefault();
          setOver(false);
          take(event.dataTransfer.files);
        }}
      >
        <span className={styles.label}>{busy ?? label}</span>
        {!busy && <span className={styles.or}>or click to choose a file ({accept.replaceAll(",", ", ")})</span>}
        <input
          ref={input}
          id={id}
          type="file"
          accept={accept}
          className={styles.input}
          disabled={Boolean(busy)}
          onChange={(event) => {
            take(event.target.files);
            event.target.value = ""; // so choosing the same file again still uploads it
          }}
        />
      </label>
      {error ? <p className={styles.error}>{error}</p> : hint && <p className={styles.hint}>{hint}</p>}
    </div>
  );
}
