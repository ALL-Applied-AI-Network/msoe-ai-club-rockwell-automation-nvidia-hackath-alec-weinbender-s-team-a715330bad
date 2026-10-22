import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, unwrap, type Schemas } from "../../backend/client";

// The quick logger's data. Keys start with ["job", id], like the validation page's, so a logged trial refreshes both.

export type LogBody = Schemas["LogTrialRequest"];

export function useJob(id: string) {
  return useQuery({
    queryKey: ["job", id, "detail"],
    queryFn: () => unwrap(api.GET("/api/jobs/{job_id}", { params: { path: { job_id: id } } })),
  });
}

export function useTestPlans(id: string, enabled: boolean) {
  return useQuery({
    queryKey: ["job", id, "test-plans"],
    queryFn: () => unwrap(api.GET("/api/jobs/{job_id}/test-plans", { params: { path: { job_id: id } } })),
    enabled,
  });
}

/** One plan with its rows and the trials logged against it. */
export function useTestPlan(id: string, planId: number | undefined) {
  return useQuery({
    queryKey: ["job", id, "test-plan", planId],
    queryFn: () =>
      unwrap(
        api.GET("/api/jobs/{job_id}/test-plans/{plan_id}", { params: { path: { job_id: id, plan_id: planId! } } }),
      ),
    enabled: planId !== undefined,
  });
}

/** Logs one trial. Logging a trial again replaces its outcome; the earlier one stays in its history. */
export function useLogTrial(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: LogBody) =>
      unwrap(api.POST("/api/jobs/{job_id}/physical", { params: { path: { job_id: id } }, body })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["job", id] }),
  });
}
