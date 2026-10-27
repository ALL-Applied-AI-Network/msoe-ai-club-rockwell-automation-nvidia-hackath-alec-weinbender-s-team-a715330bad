import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, unwrapAs, type Schemas } from "../../backend/client";
import { jobKey } from "../validation/queries";
import type { Results } from "./types";

// One experiment's queries. The keys share the validation pages' ["job", id, ...] prefix, so a change on either page
// (a print selection, a review) refreshes both.

type JobDetail = Schemas["JobDetailResponse"];
export type Rescore = Schemas["RescoreRequest"];

/** The job: its spec, plan, progress, card and review. */
export function useJobDetail(id: string) {
  return useQuery({
    queryKey: [...jobKey(id), "detail"],
    queryFn: () => unwrapAs<JobDetail>(api.GET("/api/jobs/{job_id}", { params: { path: { job_id: id } } })),
  });
}

/** The results view at the job's own error model and task. It answers during the run too: the final-test sections are
 *  null until the final test, and `run` has each search's progress. */
export function useResults(id: string) {
  return useQuery({
    queryKey: [...jobKey(id), "results"],
    queryFn: () => unwrapAs<Results>(api.GET("/api/jobs/{job_id}/results", { params: { path: { job_id: id } } })),
  });
}

/** Refetches everything about one experiment, and the experiment list. */
export function useRefresh(id: string) {
  const queryClient = useQueryClient();
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: jobKey(id) }),
      queryClient.invalidateQueries({ queryKey: ["jobs"] }),
    ]);
}
