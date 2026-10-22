import styles from "./Segmented.module.css";

type Option<T extends string> = { value: T; label: string; count?: number };

type SegmentedProps<T extends string> = {
  label: string; // what it chooses, for screen readers, e.g. "Status"
  options: Option<T>[];
  value: T;
  onChange: (value: T) => void;
};

/** A row of mutually exclusive choices, e.g. a list's status filter. Each can show how many items it holds. */
export function Segmented<T extends string>({ label, options, value, onChange }: SegmentedProps<T>) {
  return (
    <div className={styles.group} role="radiogroup" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="radio"
          aria-checked={option.value === value}
          className={styles.option}
          onClick={() => onChange(option.value)}
        >
          {option.label}
          {option.count !== undefined && <span className={styles.count}>{option.count}</span>}
        </button>
      ))}
    </div>
  );
}
