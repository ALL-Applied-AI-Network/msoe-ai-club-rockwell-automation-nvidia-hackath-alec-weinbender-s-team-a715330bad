import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, unwrap, type Schemas } from "../../backend/client";
import { useCompute } from "../../backend/queries";

// The GPU page's own data. The session status itself is useCompute() (backend/queries.ts), shared with the status bar.

type Instance = Schemas["ComputeInstance"];

/** Every enabled backend's targets. Slow (it asks Brev's CLI and ssh's into the GB10), so it has its own key: the
 *  status polls never trigger it. Refreshed every minute while connected to the shared GB10, for its load. */
export function useInstances(refreshEveryMinute: boolean) {
  return useQuery({
    queryKey: ["compute-instances"],
    queryFn: () => unwrap(api.GET("/api/compute/instances")),
    retry: false,
    staleTime: 30_000,
    refetchInterval: refreshEveryMinute ? 60_000 : false,
  });
}

/** The session log, latest first: which target was connected when, and why it ended. Fetched again whenever the live
 *  session moves on (started, ready, stopping, ended), so its row never shows a stale state. */
export function useSessions() {
  const live = useCompute().data?.session;
  const liveKey = live ? `${live.id}:${live.status}` : "none";
  const query = useQuery({
    queryKey: ["compute", "sessions"],
    queryFn: () => unwrap(api.GET("/api/compute/sessions", { params: { query: { limit: 50 } } })),
  });
  const { refetch } = query;
  useEffect(() => {
    void refetch();
  }, [liveKey, refetch]);
  return query;
}

/** Start, stop, and switch: stop the current target, wait until it has stopped, then start the chosen one. Every one
 *  refreshes the status, so the chip and the page follow at once. */
export function useComputeActions() {
  const queryClient = useQueryClient();
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["compute"] });
  const start = useMutation({
    mutationFn: (target: Instance) =>
      unwrap(api.POST("/api/compute/start", { body: { backend: target.backend, instance: target.name } })),
    onSettled: refresh,
  });
  const stop = useMutation({ mutationFn: () => unwrap(api.POST("/api/compute/stop")), onSettled: refresh });
  const switchTo = useMutation({
    mutationFn: async (target: Instance) => {
      await unwrap(api.POST("/api/compute/stop")).catch(() => undefined); // already stopped: carry on
      const deadline = Date.now() + 10 * 60_000; // a Brev instance can take minutes to stop
      for (;;) {
        const status = await unwrap(api.GET("/api/compute"));
        if (!status.session) break;
        if (Date.now() > deadline) throw new Error(`${status.session.instance} didn't stop within 10 minutes: try again.`);
        await new Promise((resolve) => setTimeout(resolve, 2_000));
        void refresh();
      }
      return unwrap(api.POST("/api/compute/start", { body: { backend: target.backend, instance: target.name } }));
    },
    onSettled: refresh,
  });
  return { start, stop, switchTo };
}

/** The time now, in Unix seconds, updated every second: for "connected for" and "starting for" counters. */
export function useNow(active = true): number {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => setNow(Date.now() / 1000), 1_000);
    return () => clearInterval(timer);
  }, [active]);
  return now;
}
