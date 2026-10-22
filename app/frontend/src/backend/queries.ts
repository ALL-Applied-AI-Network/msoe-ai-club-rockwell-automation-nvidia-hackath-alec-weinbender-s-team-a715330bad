import { useQuery } from "@tanstack/react-query";
import { api, unwrap, unwrapAs, type Schemas } from "./client";

// Queries more than one page or component reads. Each has one query key, so they share one cache entry and one poll.

/** `/api/meta`: the sim badge, demo data, materials, task kinds and the other choices. It changes only on an API restart. */
export function useMeta() {
  return useQuery({
    queryKey: ["meta"],
    queryFn: () => unwrap(api.GET("/api/meta")),
    staleTime: Infinity,
    retry: 1,
  });
}

/** `/api/compute`: the GPU session. Polled every 3 s while a session is active, every 15 s otherwise. */
export function useCompute() {
  return useQuery({
    queryKey: ["compute"],
    queryFn: () => unwrap(api.GET("/api/compute")),
    refetchInterval: (query) => (query.state.data?.session ? 3_000 : 15_000),
  });
}

type Part = Schemas["PartResponse"];

/** Every stored part, newest first, without its convex pieces. */
export function useParts() {
  return useQuery({ queryKey: ["parts"], queryFn: () => unwrapAs<Part[]>(api.GET("/api/parts")) });
}

/** One part. */
export function usePart(id: string | undefined) {
  return useQuery({
    queryKey: ["parts", id],
    queryFn: () => unwrapAs<Part>(api.GET("/api/parts/{part_id}", { params: { path: { part_id: id! } } })),
    enabled: Boolean(id),
  });
}

type CellProfile = Schemas["CellProfileResponse"];

/** Every cell profile at its latest version. */
export function useCellProfiles() {
  return useQuery({ queryKey: ["cell-profiles"], queryFn: () => unwrapAs<CellProfile[]>(api.GET("/api/cell-profiles")) });
}

/** One cell profile version: ids are per version, so an old experiment's id still shows the version it ran with. */
export function useCellProfile(id: number | null | undefined) {
  return useQuery({
    queryKey: ["cell-profiles", id],
    queryFn: () =>
      unwrapAs<CellProfile>(api.GET("/api/cell-profiles/{profile_id}", { params: { path: { profile_id: id! } } })),
    enabled: id != null,
  });
}

/** Where a part's 3D mesh is served: a binary STL in its chosen resting pose, or in `pose` ("as_authored" or an index). */
export function meshUrl(id: string, pose?: number | "as_authored"): string {
  const base = `/api/parts/${encodeURIComponent(id)}/mesh`;
  return pose === undefined ? base : `${base}?pose=${pose}`;
}
