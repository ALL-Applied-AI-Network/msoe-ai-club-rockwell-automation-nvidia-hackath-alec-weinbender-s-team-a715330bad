import styles from "./Icon.module.css";

// Every icon in the app, drawn the same way: 16 x 16, 1.5 px strokes in the current text colour. Add a path here rather
// than an icon anywhere else, and use icons only where a control really needs one; words come first.
const PATHS = {
  plus: "M8 3v10M3 8h10",
  refresh: "M13 8a5 5 0 1 1-1.5-3.6M13 2.5V5h-2.5",
  chip: "M5 5h6v6H5zM6.5 2v2M9.5 2v2M6.5 12v2M9.5 12v2M2 6.5h2M2 9.5h2M12 6.5h2M12 9.5h2",
  external: "M9 3h4v4M13 3 7.5 8.5M11 9.5V13H3V5h3.5",
  close: "M4 4l8 8M12 4l-8 8",
  gripper: "M4 2v5l2.5 2.5V14M12 2v5l-2.5 2.5V14M4 7h8",
  copy: "M5.5 5.5h7v7h-7zM3.5 10.5v-7h7",
  download: "M8 2.5v8M4.5 7 8 10.5 11.5 7M3 13.5h10",
  upload: "M8 10.5v-8M4.5 6 8 2.5 11.5 6M3 13.5h10",
  cube: "M8 2 13.5 5v6L8 14 2.5 11V5zM2.5 5 8 8l5.5-3M8 8v6",
} as const;

export type IconName = keyof typeof PATHS;

/** An inline SVG icon. Decorative unless `label` is given, which also makes it an image for screen readers. */
export function Icon({ name, label }: { name: IconName; label?: string }) {
  return (
    <svg
      className={styles.icon}
      viewBox="0 0 16 16"
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    >
      <path d={PATHS[name]} />
    </svg>
  );
}
