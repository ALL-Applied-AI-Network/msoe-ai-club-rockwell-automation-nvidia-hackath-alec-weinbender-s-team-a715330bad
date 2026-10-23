import type { Schemas } from "../../backend/client";
import { dims, quantity, trim } from "../../format";

// A cell profile's fields in words: their labels, which editor group each sits in, and what changed between two versions.

type Profile = Schemas["CellProfile"];
export type ProfileKey = keyof Profile;
export type Group = "robot" | "gripper" | "mount" | "friction" | "cameras" | "sim";

export const LABELS: Record<string, string> = {
  robot_model: "Robot model",
  tcp_offset_mm: "TCP offset",
  approach: "Approach",
  lift_m: "Lift",
  gripper_model: "Gripper model",
  stroke_per_jaw_mm: "Stroke per jaw",
  grip_force_n: "Grip force per jaw",
  air_pressure_mpa: "Air pressure",
  stock_fingers: "Stock fingers",
  stock_finger_mm: "Stock finger size",
  stock_tip_gap_mm: "Stock tip gap",
  max_finger_length_mm: "Max finger length",
  free_space_mm: "Free space beside the gripper",
  mount_kept_mm: "Mount kept as stock",
  finger_mount: "Finger mount",
  hole_clearance_mm: "Hole clearance",
  pad_material: "Pad material",
  pad_friction: "Pad friction",
  mat_friction: "Table mat friction",
  cameras: "Cameras",
  sim: "Advanced sim settings",
  // Inside finger_mount
  face: "Mount face",
  face_x_mm: "Jaw face position",
  jaw_length_mm: "Jaw length",
  jaw_clearance_mm: "Clearance below the jaw",
  face_size_mm: "Jaw face size",
  below_root_mm: "below the root",
  x_mm: "x position",
  y_mm: "y position",
  diameter_mm: "diameter",
  depth_mm: "depth",
  counterbore_diameter_mm: "counterbore diameter",
  counterbore_depth_mm: "counterbore depth",
  kind: "kind",
  length_mm: "length",
  height_mm: "height",
  // Inside cameras
  name: "name",
  width_px: "width",
  height_px: "height",
  // Inside sim
  physics_dt_s: "Physics time step",
  solver_position_iterations: "Solver position iterations",
  solver_velocity_iterations: "Solver velocity iterations",
  contact_offset_mm: "Contact offset",
  rest_offset_mm: "Rest offset",
  envs: "Environments",
};

const GROUPS: Record<Group, ProfileKey[]> = {
  robot: ["robot_model", "tcp_offset_mm", "approach", "lift_m"],
  gripper: [
    "gripper_model",
    "stroke_per_jaw_mm",
    "grip_force_n",
    "air_pressure_mpa",
    "stock_fingers",
    "stock_finger_mm",
    "stock_tip_gap_mm",
    "max_finger_length_mm",
    "free_space_mm",
    "mount_kept_mm",
  ],
  mount: ["finger_mount", "hole_clearance_mm"],
  friction: ["pad_material", "pad_friction", "mat_friction"],
  cameras: ["cameras"],
  sim: ["sim"],
};

/** The editor group a top-level field belongs to. */
export function groupOf(key: string): Group | undefined {
  return (Object.keys(GROUPS) as Group[]).find((group) => (GROUPS[group] as string[]).includes(key));
}

/** The placeholder fields, each once (a profile's `to_confirm` can name one twice). */
export function placeholders(profile: Profile): Set<string> {
  return new Set(profile.to_confirm);
}

/** A 422 from saving, as a message and the group it belongs to. Field errors carry their field in `loc`; the profile's
 *  own checks (`loc` is just the profile) are all about the mount fitting the blade. */
export function saveError(detail: unknown): { message: string; group?: Group } {
  if (typeof detail === "string") return { message: detail };
  if (!Array.isArray(detail) || detail.length === 0) return { message: "The profile couldn't be saved." };
  const first = detail[0] as { loc?: (string | number)[]; msg?: string };
  const message = (first.msg ?? "Invalid value").replace(/^Value error, /, "");
  const field = first.loc?.[2];
  if (typeof field === "string") {
    return { message: `${label((first.loc ?? []).slice(2).map(String))}: ${message}`, group: groupOf(field) };
  }
  return { message: capitalise(message), group: /jaw|mount|blade|hole|locating/.test(message) ? "mount" : undefined };
}

/** What changed from one version to the next, one line each, e.g. "Stroke per jaw: 6.0 mm to 10.0 mm". */
export function changes(before: Profile, after: Profile): string[] {
  const lines: string[] = [];
  const a = flatten(before);
  const b = flatten(after);
  const items = new Set([...a.items, ...b.items]);
  for (const item of items) {
    if (!a.items.has(item)) lines.push(`${label(item.split("."))} added`);
    else if (!b.items.has(item)) lines.push(`${label(item.split("."))} removed`);
  }
  const paths = new Set([...a.leaves.keys(), ...b.leaves.keys()]);
  for (const path of paths) {
    const parts = path.split(".");
    if ([...items].some((item) => (path.startsWith(`${item}.`) && !(a.items.has(item) && b.items.has(item))))) continue;
    const from = a.leaves.get(path);
    const to = b.leaves.get(path);
    if (JSON.stringify(from) === JSON.stringify(to)) continue;
    lines.push(`${label(parts)}: ${show(parts.at(-1)!, from)} to ${show(parts.at(-1)!, to)}`);
  }
  const measured = [...placeholders(before)].filter((key) => !placeholders(after).has(key));
  const marked = [...placeholders(after)].filter((key) => !placeholders(before).has(key));
  if (measured.length) lines.push(`Marked as measured: ${measured.map((key) => LABELS[key] ?? key).join(", ")}`);
  if (marked.length) lines.push(`Marked as a placeholder: ${marked.map((key) => LABELS[key] ?? key).join(", ")}`);
  return lines;
}

type Leaf = string | number | boolean | null | number[];

/** Every leaf value by its dotted path, and every item of a list of objects (mount holes, cameras) by its path. Lists of
 *  numbers (sizes, friction pairs) are one value. */
function flatten(profile: Profile) {
  const leaves = new Map<string, Leaf>();
  const items = new Set<string>();
  const walk = (value: unknown, path: string[]) => {
    if (Array.isArray(value) && value.every((v) => typeof v === "number")) {
      leaves.set(path.join("."), value as number[]);
    } else if (Array.isArray(value)) {
      value.forEach((item, i) => {
        items.add([...path, String(i)].join("."));
        walk(item, [...path, String(i)]);
      });
    } else if (value !== null && typeof value === "object") {
      for (const [key, v] of Object.entries(value)) walk(v, [...path, key]);
    } else {
      leaves.set(path.join("."), (value ?? null) as Leaf);
    }
  };
  const { to_confirm: _, ...rest } = profile;
  walk(rest, []);
  return { leaves, items };
}

/** A path in words: "Mount hole 2 diameter", "Camera 1 width", "Environments". */
function label(parts: string[]): string {
  const words: string[] = [];
  for (let i = 0; i < parts.length; i++) {
    const part = parts[i];
    const next = parts[i + 1];
    if (part === "finger_mount" || part === "sim") continue;
    if (part === "holes" && next) words.push(`Mount hole ${Number(next) + 1}`);
    else if (part === "locating" && next) words.push(`Locating feature ${Number(next) + 1}`);
    else if (part === "cameras" && next) words.push(`Camera ${Number(next) + 1}`);
    else if (/^\d+$/.test(part)) continue;
    else words.push(LABELS[part] ?? part);
  }
  return capitalise(words.join(" "));
}

/** A value in words with its unit, from its field's name. */
function show(key: string, value: Leaf | undefined): string {
  if (value === undefined || value === null || value === "") return "not set";
  if (Array.isArray(value)) {
    if (key.endsWith("_friction")) return `${trim(value[0])} static, ${trim(value[1])} sliding`;
    return key.endsWith("_mm") ? dims(value) : value.map((v) => trim(v)).join(" and ");
  }
  if (typeof value !== "number") return String(value);
  if (key.endsWith("_mm")) return quantity(value, "mm");
  if (key.endsWith("_mpa")) return quantity(value, "MPa");
  if (key.endsWith("_n")) return quantity(value, "N");
  if (key.endsWith("_m")) return quantity(value, "m");
  if (key.endsWith("_s")) return quantity(value, "s");
  if (key.endsWith("_px")) return quantity(value, "px");
  return trim(value, 4);
}

function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}
