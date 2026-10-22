import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, unwrap } from "../../backend/client";

// One experiment's results-tracker data. Every key starts with ["job", id], so a change invalidates them all at once.

export const jobKey = (id: string) => ["job", id] as const;

export function useJob(id: string) {
  return useQuery({
    queryKey: [...jobKey(id), "detail"],
    queryFn: () => unwrap(api.GET("/api/jobs/{job_id}", { params: { path: { job_id: id } } })),
  });
}

/** The results view, for the final-test table (null before the final test). */
export function useResults(id: string, enabled: boolean) {
  return useQuery({
    queryKey: [...jobKey(id), "results"],
    queryFn: () => unwrap(api.GET("/api/jobs/{job_id}/results", { params: { path: { job_id: id } } })),
    enabled,
  });
}

export function usePrintSelection(id: string, enabled: boolean) {
  return useQuery({
    queryKey: [...jobKey(id), "print-selection"],
    queryFn: () => unwrap(api.GET("/api/jobs/{job_id}/print-selection", { params: { path: { job_id: id } } })),
    enabled,
  });
}

export function usePrintedFingers(id: string, enabled: boolean) {
  return useQuery({
    queryKey: [...jobKey(id), "printed-fingers"],
    queryFn: () => unwrap(api.GET("/api/jobs/{job_id}/printed-fingers", { params: { path: { job_id: id } } })),
    enabled,
  });
}

/** The experiment's test plans, newest last. Polled every 2 s while a plan's sim prediction is still running. */
export function useTestPlans(id: string, enabled: boolean) {
  return useQuery({
    queryKey: [...jobKey(id), "test-plans"],
    queryFn: () => unwrap(api.GET("/api/jobs/{job_id}/test-plans", { params: { path: { job_id: id } } })),
    enabled,
    refetchInterval: (query) =>
      query.state.data?.some((plan) => plan.prediction_status === "pending" || plan.prediction_status === "running")
        ? 2_000
        : false,
  });
}

export function useValidation(id: string, enabled = true) {
  return useQuery({
    queryKey: [...jobKey(id), "validation"],
    queryFn: () => unwrap(api.GET("/api/jobs/{job_id}/validation", { params: { path: { job_id: id } } })),
    enabled,
  });
}

/** Refetches everything about one experiment, and the experiment list (its physical badge may have changed). */
export function useRefreshJob(id: string) {
  const queryClient = useQueryClient();
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: jobKey(id) }),
      queryClient.invalidateQueries({ queryKey: ["jobs"] }),
    ]);
}
