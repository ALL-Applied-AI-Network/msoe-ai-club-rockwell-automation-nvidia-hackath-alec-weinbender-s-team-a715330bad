import { useId, useRef, useState, type ReactNode } from "react";
import styles from "./FileDrop.module.css";

type FileDropProps = {
  label: string; // what to drop, e.g. "Drop a STEP or STL file"
  accept: string; // file extensions, e.g. ".step,.stp,.stl"
  hint?: ReactNode; // shown before anyone tries, e.g. the SolidWorks export hint
  busy?: string; // while uploading: what's happening, e.g. "Reading the part"
  error?: string;
  onFile?: (file: File) => void; // one file
  onFiles?: (files: File[]) => void; // or many: several chosen or dropped at once
  folder?: boolean; // with onFiles: the chooser picks a folder, and every file in it is sent
};

/** Drop a file here or choose one: the CAD upload and the test-plan spreadsheet upload. */
export function FileDrop({ label, accept, hint, busy, error, onFile, onFiles, folder = false }: FileDropProps) {
  const input = useRef<HTMLInputElement>(null);
  const id = useId();
  const [over, setOver] = useState(false);
  const take = (files: FileList | null) => {
    if (!files?.length || busy) return;
    if (onFiles) onFiles(Array.from(files));
    else onFile?.(files[0]);
  };
  // A folder chooser is a browser extension of <input type="file">, missing from React's types.
  const pickFolder = folder ? ({ webkitdirectory: "", directory: "" } as Record<string, string>) : {};

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
        {!busy && (
          <span className={styles.or}>
            {folder ? "or click to choose a folder" : onFiles ? "or click to choose files" : "or click to choose a file"} (
            {accept.replaceAll(",", ", ")})
          </span>
        )}
        <input
          ref={input}
          id={id}
          type="file"
          accept={folder ? undefined : accept}
          multiple={Boolean(onFiles)}
          {...pickFolder}
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
