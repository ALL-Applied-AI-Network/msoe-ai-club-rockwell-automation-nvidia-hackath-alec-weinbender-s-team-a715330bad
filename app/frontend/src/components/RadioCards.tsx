import { useId, type ReactNode } from "react";
import styles from "./RadioCards.module.css";

export type RadioCard<T extends string> = {
  value: T;
  label: string;
  description?: ReactNode; // a line or two under the label
  aside?: ReactNode; // at the right of the label, e.g. a "Placeholder" badge
  disabled?: boolean;
};

type RadioCardsProps<T extends string> = {
  label: string; // what it chooses, for screen readers, e.g. "Task"
  options: RadioCard<T>[];
  value: T | undefined;
  onChange: (value: T) => void;
  onHighlight?: (value: T | undefined) => void; // the card hovered or focused, e.g. to preview its video
  columns?: number; // cards per row on wide screens; they stack on narrow ones
};

/** A choice between a few options that each need a sentence to explain: the task kinds, the camera-error presets. Real
 *  radio inputs underneath, so the arrow keys move between cards. */
export function RadioCards<T extends string>({ label, options, value, onChange, onHighlight, columns = 3 }: RadioCardsProps<T>) {
  const name = useId();
  return (
    <div
      className={styles.group}
      role="radiogroup"
      aria-label={label}
      style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}
      onMouseLeave={() => onHighlight?.(undefined)}
    >
      {options.map((option) => (
        <label
          key={option.value}
          className={[styles.card, option.value === value && styles.checked, option.disabled && styles.disabled]
            .filter(Boolean)
            .join(" ")}
          onMouseEnter={() => onHighlight?.(option.value)}
        >
          <input
            type="radio"
            className={styles.input}
            name={name}
            value={option.value}
            checked={option.value === value}
            disabled={option.disabled}
            onChange={() => onChange(option.value)}
            onFocus={() => onHighlight?.(option.value)}
            onBlur={() => onHighlight?.(undefined)}
          />
          <span className={styles.top}>
            <span className={styles.dot} aria-hidden="true" />
            <span className={styles.label}>{option.label}</span>
            {option.aside && <span className={styles.aside}>{option.aside}</span>}
          </span>
          {option.description && <span className={styles.description}>{option.description}</span>}
        </label>
      ))}
    </div>
  );
}
