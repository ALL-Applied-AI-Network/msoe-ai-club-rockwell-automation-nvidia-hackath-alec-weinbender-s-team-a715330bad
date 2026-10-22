import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, unwrap, type Schemas } from "../../../backend/client";
import type { Tone } from "../../../components/Badge";
import type { Results } from "../types";

// The Isaac Sim clips' data and the grasps worth filming (docs/notes/frontend-plan.md 7.5, backend-api.md "Isaac Sim
// clips").

export type Clip = Schemas["Clip"];
export type Offset = Schemas["ClipOffset"];

export const CLIP_STATUS: Record<Clip["status"], { tone: Tone; label: string }> = {
  queued: { tone: "neutral", label: "Queued" },
  recording: { tone: "active", label: "Recording" },
  ready: { tone: "ok", label: "Ready" },
  failed: { tone: "bad", label: "Failed" },
};

/** The experiment's clips, newest first. Polled every 3 s while any is queued or recording. */
export function useClips(jobId: string, enabled: boolean) {
  return useQuery({
    queryKey: ["job", jobId, "clips"],
    queryFn: () => unwrap(api.GET("/api/jobs/{job_id}/clips", { params: { path: { job_id: jobId } } })),
    enabled,
    refetchInterval: (query) =>
      query.state.data?.some((clip) => clip.status === "queued" || clip.status === "recording") ? 3_000 : false,
  });
}

/** Asks for one clip of each design at one offset. Asking again for a clip that exists returns it, unless it failed. */
export function useRecord(jobId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ designs, at }: { designs: string[]; at: Offset }) => {
      for (const design of designs) {
        await unwrap(
          api.POST("/api/jobs/{job_id}/clips", { params: { path: { job_id: jobId } }, body: { design, offset: at } }),
        );
      }
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["job", jobId, "clips"] }),
  });
}

/** Where a ready clip's video is served, in one of its two views. */
export function clipUrl(jobId: string, clip: Clip, view: "closeup" | "side"): string {
  return `/api/jobs/${encodeURIComponent(jobId)}/clips/${clip.id}.mp4?view=${view}`;
}

/** The same grid point: offsets come back as floats, so they're compared to a micrometre. */
export function sameOffset(a: Offset, b: Offset): boolean {
  return Math.abs(a.dx - b.dx) < 1e-3 && Math.abs(a.dy - b.dy) < 1e-3 && Math.abs(a.yaw_deg - b.yaw_deg) < 1e-3;
}

/** The newest clip of a design at an offset, if any (the list is newest first). */
export function findClip(clips: Clip[], design: string, at: Offset): Clip | undefined {
  return clips.find((clip) => clip.design.toUpperCase() === design.toUpperCase() && sameOffset(clip.offset, at));
}

export type Suggestion = { key: string; label: string; why: string; at: Offset };

/** The grasps worth filming for a design (plan 7.5): the centre, the edge of what it catches, and the nearest one it
 *  misses, all at zero yaw, from its held map on the final grid. */
export function suggestions(results: Results, design: string): Suggestion[] {
  const map = results.held_maps.find((m) => m.label.toUpperCase() === design.toUpperCase());
  if (!map) return [];
  const points = map.points.filter((p) => Math.abs(p.yaw_deg) < 1e-9);
  const radius = (p: { dx: number; dy: number }) => Math.hypot(p.dx, p.dy);
  const at = (p: { dx: number; dy: number; yaw_deg: number }): Offset => ({ dx: p.dx, dy: p.dy, yaw_deg: p.yaw_deg });
  const out: Suggestion[] = [];
  const centre = [...points].sort((a, b) => radius(a) - radius(b))[0];
  if (centre) out.push({ key: "centre", label: "The centre", why: "No camera error at all.", at: at(centre) });
  const firstMiss = points.filter((p) => !p.held).sort((a, b) => radius(a) - radius(b))[0];
  const edge = points
    .filter((p) => p.held && (!firstMiss || radius(p) < radius(firstMiss)))
    .sort((a, b) => radius(b) - radius(a))[0];
  if (edge && (!centre || !sameOffset(at(edge), at(centre)))) {
    out.push({ key: "edge", label: "The capture edge", why: "The farthest grasp it holds before any miss.", at: at(edge) });
  }
  if (firstMiss) out.push({ key: "miss", label: "A miss", why: "The nearest grasp it drops.", at: at(firstMiss) });
  return out;
}

/** The experiment's stored outcome for a design at an offset, if that's a point of the final grid. */
export function storedOutcome(results: Results, design: string, at: Offset): boolean | undefined {
  const map = results.held_maps.find((m) => m.label.toUpperCase() === design.toUpperCase());
  const point = map?.points.find((p) => sameOffset({ dx: p.dx, dy: p.dy, yaw_deg: p.yaw_deg }, at));
  return point?.held;
}
