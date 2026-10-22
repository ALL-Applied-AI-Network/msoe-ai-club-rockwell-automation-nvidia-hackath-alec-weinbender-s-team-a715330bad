import type { ReactNode, SelectHTMLAttributes } from "react";
import { Field, fieldStyles } from "./Field";

type SelectProps = SelectHTMLAttributes<HTMLSelectElement> & {
  label: string;
  options: { value: string; label: string; disabled?: boolean }[];
  placeholder?: string; // shown first, with an empty value, until something is chosen
  hint?: ReactNode;
  error?: string;
  isPlaceholder?: boolean; // the value isn't measured yet: marks the field "Placeholder"
};

/** A labelled dropdown. */
export function Select({ label, options, placeholder, hint, error, isPlaceholder, ...props }: SelectProps) {
  return (
    <Field label={label} hint={hint} error={error} isPlaceholder={isPlaceholder}>
      {(id) => (
        <select id={id} className={fieldStyles.control} {...props}>
          {placeholder !== undefined && <option value="">{placeholder}</option>}
          {options.map((option) => (
            <option key={option.value} value={option.value} disabled={option.disabled}>
              {option.label}
            </option>
          ))}
        </select>
      )}
    </Field>
  );
}
