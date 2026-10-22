import { useId, type ReactNode } from "react";
import { Button } from "./Button";
import styles from "./RangeSlider.module.css";

type Common = {
  label: string;
  min: number;
  max: number;
  step?: number;
  format: (value: number) => string; // the value with its unit, through format.ts
  hint?: ReactNode; // what the parameter is, under the slider
  aside?: ReactNode; // at the right of the label
  disabled?: boolean;
  onFocusChange?: (focused: boolean) => void; // e.g. to preview this parameter while its slider has focus
};

type RangeSliderProps = Common & {
  value: readonly [number, number];
  onChange: (value: [number, number]) => void;
  locked?: number | null; // a single fixed value instead of a range
  onLockChange?: (value: number | null) => void; // shows the Lock toggle; null unlocks
};

/** A range over a parameter's buildable limits, with two thumbs; or, locked, one fixed value. The finger parameters in
 *  the wizard's step 6, and a range of camera errors in step 7. Each thumb is a real range input, so keyboards and
 *  screen readers work as they do on any slider. */
export function RangeSlider({
  label,
  min,
  max,
  step = stepFor(min, max),
  format,
  hint,
  aside,
  disabled = false,
  onFocusChange,
  value,
  onChange,
  locked = null,
  onLockChange,
}: RangeSliderProps) {
  const id = useId();
  const isLocked = locked != null;
  const [lo, hi] = [clamp(value[0], min, max), clamp(value[1], min, max)];
  const at = (v: number) => (max > min ? ((v - min) / (max - min)) * 100 : 0);
  const focus = {
    onFocus: () => onFocusChange?.(true),
    onBlur: () => onFocusChange?.(false),
    onPointerDown: () => onFocusChange?.(true),
  };

  return (
    <div className={`${styles.slider} ${disabled ? styles.disabled : ""}`}>
      <div className={styles.top}>
        <label className={styles.label} htmlFor={`${id}-lo`}>
          {label}
        </label>
        <span className={styles.value}>{isLocked ? `fixed at ${format(locked)}` : `${format(lo)} to ${format(hi)}`}</span>
        {aside}
        {onLockChange && (
          <Button
            variant="ghost"
            size="sm"
            disabled={disabled}
            aria-pressed={isLocked}
            onClick={() => onLockChange(isLocked ? null : snap((lo + hi) / 2, min, step))}
          >
            {isLocked ? "Unlock" : "Lock"}
          </Button>
        )}
      </div>
      <div className={styles.track}>
        <div
          className={styles.fill}
          style={isLocked ? { left: `${at(locked)}%`, width: 0 } : { left: `${at(lo)}%`, width: `${at(hi) - at(lo)}%` }}
        />
        {isLocked ? (
          <input
            id={`${id}-lo`}
            type="range"
            className={styles.input}
            min={min}
            max={max}
            step={step}
            value={clamp(locked, min, max)}
            disabled={disabled}
            aria-label={`${label}, fixed value`}
            aria-valuetext={format(locked)}
            onChange={(event) => onLockChange?.(Number(event.target.value))}
            {...focus}
          />
        ) : (
          <>
            <input
              id={`${id}-lo`}
              type="range"
              className={styles.input}
              min={min}
              max={max}
              step={step}
              value={lo}
              disabled={disabled}
              aria-label={`${label}, lowest`}
              aria-valuetext={format(lo)}
              onChange={(event) => onChange([Math.min(Number(event.target.value), hi), hi])}
              {...focus}
            />
            <input
              type="range"
              className={styles.input}
              min={min}
              max={max}
              step={step}
              value={hi}
              disabled={disabled}
              aria-label={`${label}, highest`}
              aria-valuetext={format(hi)}
              onChange={(event) => onChange([lo, Math.max(Number(event.target.value), lo)])}
              {...focus}
            />
          </>
        )}
      </div>
      <div className={styles.limits} aria-hidden="true">
        <span>{format(min)}</span>
        <span>{format(max)}</span>
      </div>
      {hint && <div className={styles.hint}>{hint}</div>}
    </div>
  );
}

type ValueSliderProps = Common & {
  value: number;
  onChange: (value: number) => void;
};

/** One value on a slider, e.g. the camera error's sigma. */
export function ValueSlider({
  label,
  min,
  max,
  step = stepFor(min, max),
  format,
  hint,
  aside,
  disabled = false,
  onFocusChange,
  value,
  onChange,
}: ValueSliderProps) {
  const id = useId();
  const v = clamp(value, min, max);
  const at = max > min ? ((v - min) / (max - min)) * 100 : 0;
  return (
    <div className={`${styles.slider} ${disabled ? styles.disabled : ""}`}>
      <div className={styles.top}>
        <label className={styles.label} htmlFor={id}>
          {label}
        </label>
        <span className={styles.value}>{format(value)}</span>
        {aside}
      </div>
      <div className={styles.track}>
        <div className={styles.fill} style={{ left: 0, width: `${at}%` }} />
        <input
          id={id}
          type="range"
          className={styles.input}
          min={min}
          max={max}
          step={step}
          value={v}
          disabled={disabled}
          aria-valuetext={format(value)}
          onChange={(event) => onChange(Number(event.target.value))}
          onFocus={() => onFocusChange?.(true)}
          onBlur={() => onFocusChange?.(false)}
        />
      </div>
      <div className={styles.limits} aria-hidden="true">
        <span>{format(min)}</span>
        <span>{format(max)}</span>
      </div>
      {hint && <div className={styles.hint}>{hint}</div>}
    </div>
  );
}

/** About a hundred steps across the range, on a round number: 0.05 mm for a few mm, 1 degree for 120 degrees. */
function stepFor(min: number, max: number): number {
  const raw = (max - min) / 100;
  if (raw <= 0) return 1;
  const power = 10 ** Math.floor(Math.log10(raw));
  return [1, 2, 5, 10].map((m) => m * power).find((s) => s >= raw) ?? raw;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function snap(value: number, min: number, step: number): number {
  return Number((min + Math.round((value - min) / step) * step).toFixed(6));
}
