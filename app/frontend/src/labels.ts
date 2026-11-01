// Names the backend sends as codes, written out for people.

/** The new-experiment wizard's steps, in order. A failed job's `failed_step` (1 to 8) indexes this list. */
export const WIZARD_STEPS = [
  { slug: "part", label: "Part" },
  { slug: "pose", label: "Pose" },
  { slug: "task", label: "Task" },
  { slug: "cell", label: "Cell" },
  { slug: "grasp", label: "Grasp" },
  { slug: "families", label: "Fingers" },
  { slug: "error", label: "Camera" },
  { slug: "review", label: "Review" },
] as const;

/** The wizard step a `failed_step` number points at, or undefined when it's out of range. */
export function wizardStep(n: number | null | undefined) {
  return n ? WIZARD_STEPS[n - 1] : undefined;
}

/** A final design's label as people say it: "D1", "Stock", "Imprint". */
export function designLabel(label: string): string {
  if (label === "STOCK") return "Stock";
  if (label === "IMP") return "Imprint";
  return label;
}

const PARAM_LABELS: Record<string, string> = {
  pad_width_mm: "Pad width",
  groove_angle_deg: "Groove angle",
  groove_depth_mm: "Groove depth",
  slack_mm: "Slack",
  tip_height_mm: "Tip height",
  lead_in_mm: "Lead-in",
};

/** A finger parameter's name as people say it: "pad_width_mm" is "Pad width". */
export function paramLabel(name: string): string {
  return PARAM_LABELS[name] ?? name.replace(/_(mm|deg)$/, "").replaceAll("_", " ").replace(/^./, (c) => c.toUpperCase());
}

/** How a search runs, from the plan's `method`. */
export function searchMethodLabel(method: "single" | "sobol" | "bo"): string {
  return { single: "Single evaluation", sobol: "Sweep", bo: "Bayesian search" }[method];
}

/** A job's kind as people say it: the stage column of the job lists. */
export const JOB_KINDS = {
  evaluation: "Finger evaluation",
  generation: "Finger generation",
} as const;

/** Where a library finger came from. */
export const FINGER_SOURCES = {
  stock: "Installed",
  generated: "Generated",
  uploaded: "Uploaded",
} as const;

/** A finger family as people say it. */
export const FINGER_FAMILIES: Record<string, string> = {
  stock: "Hooked-tip blade",
  vpad: "V-pad",
  flat: "Flat pad",
  imprint: "Imprint",
  other: "Other",
};
