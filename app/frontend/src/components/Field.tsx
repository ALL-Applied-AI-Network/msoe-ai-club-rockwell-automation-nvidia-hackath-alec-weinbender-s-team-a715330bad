import { useId, type InputHTMLAttributes, type ReactNode } from "react";
import { CAVEATS } from "../caveats";
import { Badge } from "./Badge";
import styles from "./Field.module.css";

type FieldProps = {
  label: string;
  hint?: ReactNode; // a line under the control: what it's for, or its default
  error?: string; // what's wrong with the value; replaces the hint
  isPlaceholder?: boolean; // the value isn't measured yet (a cell profile's to_confirm): marks it "Placeholder"
  aside?: ReactNode; // at the right of the label, e.g. a "Clear the placeholder mark" button
  inline?: boolean; // in a filter bar: the label is for screen readers only, so the control lines up with the chips
  children: (id: string) => ReactNode; // the control, given the id its label points at
};

/** A labelled form control with its hint or error. Every input, select and number field sits in one, so they all line
 *  up and read the same. */
export function Field({ label, hint, error, isPlaceholder = false, aside, inline = false, children }: FieldProps) {
  const id = useId();
  return (
    <div className={`${styles.field} ${inline ? styles.inline : ""}`}>
      <div className={inline ? styles.hidden : styles.top}>
        <label className={styles.label} htmlFor={id}>
          {label}
        </label>
        {isPlaceholder && <Badge tone="warn" label="Placeholder" title={CAVEATS.placeholderCell} />}
        {aside && <span className={styles.aside}>{aside}</span>}
      </div>
      {children(id)}
      {error ? <p className={styles.error}>{error}</p> : hint && <p className={styles.hint}>{hint}</p>}
    </div>
  );
}

type Common = Omit<FieldProps, "children">;

/** A one-line text field. */
export function TextInput({
  label,
  hint,
  error,
  isPlaceholder,
  aside,
  value,
  onChange,
  ...input
}: Common & Omit<InputHTMLAttributes<HTMLInputElement>, "onChange" | "value"> & {
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <Field label={label} hint={hint} error={error} isPlaceholder={isPlaceholder} aside={aside}>
      {(id) => (
        <input
          id={id}
          className={`${styles.control} ${error ? styles.invalid : ""}`}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          {...input}
        />
      )}
    </Field>
  );
}

/** A number with its unit shown inside the field ("mm", "g", "N"). Empty means null: "not set" or "use the default". */
export function NumberInput({
  label,
  hint,
  error,
  isPlaceholder,
  aside,
  value,
  onChange,
  unit,
  ...input
}: Common & Omit<InputHTMLAttributes<HTMLInputElement>, "onChange" | "value" | "type"> & {
  value: number | null | undefined;
  onChange: (value: number | null) => void;
  unit?: string;
}) {
  return (
    <Field label={label} hint={hint} error={error} isPlaceholder={isPlaceholder} aside={aside}>
      {(id) => (
        <div className={`${styles.withUnit} ${error ? styles.invalid : ""}`}>
          <input
            id={id}
            type="number"
            inputMode="decimal"
            className={styles.bare}
            value={value ?? ""}
            onChange={(event) => onChange(event.target.value === "" ? null : Number(event.target.value))}
            {...input}
          />
          {unit && <span className={styles.unit}>{unit}</span>}
        </div>
      )}
    </Field>
  );
}

/** A tick box with its label beside it, and an optional hint under it. */
export function Checkbox({
  label,
  hint,
  checked,
  onChange,
  disabled,
}: {
  label: string;
  hint?: ReactNode;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
}) {
  const id = useId();
  return (
    <div className={styles.check}>
      <input id={id} type="checkbox" checked={checked} disabled={disabled} onChange={(event) => onChange(event.target.checked)} />
      <div>
        <label htmlFor={id} className={styles.checkLabel}>
          {label}
        </label>
        {hint && <p className={styles.hint}>{hint}</p>}
      </div>
    </div>
  );
}

export { styles as fieldStyles };
