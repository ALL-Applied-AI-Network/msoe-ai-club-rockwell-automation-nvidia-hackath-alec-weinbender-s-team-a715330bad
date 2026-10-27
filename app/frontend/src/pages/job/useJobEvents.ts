import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import type { Schemas } from "../../backend/client";
import { isActive } from "../../components/Badges";

type JobCard = Schemas["JobCard"];

/** Follows one running job's card over its SSE stream (`/api/jobs/{id}/events`) and writes each update into the job
 *  list's cache. The stream closes when the job finishes, or when `enabled` turns false (the card left the screen, or
 *  the page fell back to polling). EventSource reconnects by itself if the API restarts. `onCard` also gets every
 *  card, e.g. for the experiment page to refresh its results when the round changes. */
export function useJobEvents(id: string, enabled: boolean, onCard?: (card: JobCard) => void) {
  const queryClient = useQueryClient();
  const callback = useRef(onCard);
  callback.current = onCard;
  useEffect(() => {
    if (!enabled) return;
    const source = new EventSource(`/api/jobs/${encodeURIComponent(id)}/events`);
    source.onmessage = (event: MessageEvent<string>) => {
      const card = JSON.parse(event.data) as JobCard;
      queryClient.setQueryData<JobCard[]>(["jobs"], (cards) => cards?.map((c) => (c.id === card.id ? card : c)));
      callback.current?.(card);
      if (!isActive(card.status)) {
        source.close(); // before the server ends the stream, so EventSource doesn't reconnect to a finished job
        void queryClient.invalidateQueries({ queryKey: ["jobs"] });
      }
    };
    return () => source.close();
  }, [id, enabled, queryClient]);
}
