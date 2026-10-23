import { useQuery } from "@tanstack/react-query";
import { api, unwrapAs, type Schemas } from "../../backend/client";
import { percent } from "../../format";
import type { DraftPose, PoseChoice } from "./draft";

// The part's resting poses as steps 2 and 5, the review and the summary rail show them. A job scores every ticked pose,
// weighted by its likelihood renormalised over the ticked ones (docs/notes/backend-api.md, step 2).

export type Pose = Schemas["PoseResponse"];

/** GET /api/parts/{id}/poses: the likeliest stable poses, most likely first, then "as in the CAD file". */
export function usePoses(partId: string | undefined) {
  return useQuery({
    queryKey: ["parts", partId, "poses"],
    queryFn: () => unwrapAs<Pose[]>(api.GET("/api/parts/{part_id}/poses", { params: { path: { part_id: partId! } } })),
    enabled: Boolean(partId),
  });
}

/** What the API takes for a pose: its index, or "as_authored". */
export function choiceOf(pose: Pose): PoseChoice {
  return pose.source === "as_authored" ? "as_authored" : pose.index;
}

export function findPose(poses: Pose[] | undefined, choice: PoseChoice): Pose | undefined {
  return poses?.find((p) => choiceOf(p) === choice);
}

/** The ticked poses, most likely first: the first is the primary, which sets the finger's shape. */
export function sortByLikelihood(ticked: DraftPose[], poses: Pose[]): DraftPose[] {
  const p = (d: DraftPose) => findPose(poses, d.pose)?.probability ?? -1;
  return [...ticked].sort((a, b) => p(b) - p(a));
}

/** Each ticked pose's share of the score: its likelihood over the ticked poses' total (one pose: all of it). */
export function weightOf(choice: PoseChoice, ticked: DraftPose[], poses: Pose[]): number {
  if (ticked.length <= 1) return 1;
  const total = ticked.reduce((sum, d) => sum + (findPose(poses, d.pose)?.probability ?? 0), 0);
  return total > 0 ? (findPose(poses, choice)?.probability ?? 0) / total : 1 / ticked.length;
}

/** "Lying on its side 62%, standing 38%", or just the label for one pose. */
export function posesText(ticked: DraftPose[], poses: Pose[]): string {
  return ticked
    .map((d) => {
      const label = findPose(poses, d.pose)?.label ?? "unknown pose";
      return ticked.length > 1 ? `${label} ${percent(weightOf(d.pose, ticked, poses))}` : label;
    })
    .map((text, i) => (i === 0 ? capitalise(text) : text))
    .join(", ");
}

export function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}
