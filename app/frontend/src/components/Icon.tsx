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
  home: "M2.5 7.5 8 3l5.5 4.5V13.5H10V10H6v3.5H2.5z",
  list: "M6 4h7.5M6 8h7.5M6 12h7.5M2.5 4h1M2.5 8h1M2.5 12h1",
  grid: "M2.5 2.5h4.5v4.5H2.5zM9 2.5h4.5v4.5H9zM2.5 9h4.5v4.5H2.5zM9 9h4.5v4.5H9z",
  bolt: "M9 1.5 3.5 9h4L7 14.5 12.5 7h-4z",
  arm: "M2.5 14h6M5.5 14v-2.5M5.5 11.5 9 6.5M9 6.5l3.5-2M12.5 4.5l1 1.5M12.5 4.5l-1-1.5M6.5 11.5a1 1 0 1 1-2 0 1 1 0 0 1 2 0zM10 6.5a1 1 0 1 1-2 0 1 1 0 0 1 2 0z",
  chevron: "M6 3.5 10.5 8 6 12.5",
  arrow: "M3 8h10M9 4l4 4-4 4",
  search: "M7 12a5 5 0 1 0 0-10 5 5 0 0 0 0 10zM10.5 10.5 14 14",
  clock: "M8 14a6 6 0 1 0 0-12 6 6 0 0 0 0 12zM8 5v3l2 1.5",
  more: "M8 3.5v.01M8 8v.01M8 12.5v.01",
  cloud: "M5 12.5H4.5a3 3 0 0 1-.4-6 4.5 4.5 0 0 1 8.6 1.2A2.4 2.4 0 0 1 12 12.5h-1M8 8.5v5M6 10.5l2-2 2 2",
  "plus-box": "M2.5 2.5h11v11h-11zM8 5v6M5 8h6",
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
