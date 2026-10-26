import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { useParams } from "react-router";
import type { Schemas } from "../../backend/client";
import { canResume, isActive } from "../../components/Badges";
import { Page } from "../../components/Page";
import { EmptyState, ErrorState, Skeleton } from "../../components/States";
import { EvaluationResults } from "./evaluation/EvaluationResults";
import { useJobEvents } from "./useJobEvents";
import { jobKey } from "../validation/queries";
import { BestFingerSection } from "./finger/BestFingerSection";
import { JobHeader } from "./JobHeader";
import { Progress, SearchCard } from "./Progress";
import { useJobDetail, useResults } from "./queries";
import { ResultBanners } from "./sections/Banners";
import { FinalTest } from "./sections/FinalTest";
import { Physical } from "./sections/Physical";
import { Evidence } from "./sections/Evidence";
import { Summary } from "./sections/Summary";
import { Stopped } from "./Stopped";
import type { ClipPick } from "./types";

type JobCard = Schemas["JobCard"];

/** #/jobs/:id: one job at one address, followed live while it runs. A generation job shows its designs
 *  (frontend-plan.md 6.2, 6.3, 7); an evaluation job shows the library's fingers ranked (EvaluationResults). */
export function JobPage() {
  const { id = "" } = useParams();
  const queryClient = useQueryClient();
  const detail = useJobDetail(id);

  // Follow a running job over its event stream: each card updates the page, and a new round or status refreshes
  // everything about the job (its results, its ranking).
  const card = detail.data?.card;
  const seen = useRef("");
  useJobEvents(id, Boolean(card && isActive(card.status)), (next: JobCard) => {
    queryClient.setQueryData<Schemas["JobDetailResponse"]>([...jobKey(id), "detail"], (job) => (job ? { ...job, card: next } : job));
    const step = `${next.status}/${next.round}`;
    if (step !== seen.current) {
      seen.current = step;
      void queryClient.invalidateQueries({ queryKey: jobKey(id) });
    }
  });

  if (detail.isPending) {
    return (
      <Page>
        <Skeleton height={140} />
        <Skeleton height={320} />
      </Page>
    );
  }
  if (detail.isError) {
    return (
      <Page title="Job">
        <ErrorState title="Couldn't load this job" message={detail.error.message} onRetry={() => void detail.refetch()} />
      </Page>
    );
  }
  return detail.data.kind === "evaluation" ? <EvaluationResults job={detail.data} /> : <GenerationResults job={detail.data} />;
}

/** A generation job: live progress, then the designs, answer first and evidence after. The same sections fill in as the
 *  run finishes, so the layout doesn't jump. */
function GenerationResults({ job }: { job: Schemas["JobDetailResponse"] }) {
  const id = job.id;
  const results = useResults(id);
  const [picked, setPicked] = useState<ClipPick | null>(null);

  const status = job.card.status;
  const shown = results.data;
  const done = Boolean(shown?.summary);

  return (
    <Page header={<JobHeader job={job} results={shown} />}>
      {isActive(status) && <Progress job={job} results={shown} />}
      {canResume(status) && <Stopped card={job.card} />}

      {results.isError && (
        <ErrorState title="Couldn't load the results" message={results.error.message} onRetry={() => void results.refetch()} />
      )}

      {shown && done && (
        <>
          <ResultBanners job={job} results={shown} />
          <Summary results={shown} />
          <BestFingerSection jobId={id} results={shown} />
          {shown.final_table.length > 0 && <FinalTest jobId={id} results={shown} />}
          <Physical jobId={id} results={shown} />
          <Evidence jobId={id} results={shown} picked={picked} onPicked={setPicked} />
        </>
      )}

      {shown && !done && (
        <>
          {canResume(status) && <SearchCard searches={shown.run.searches} />}
          <EmptyState title="Results appear after the final test">
            {canResume(status) ? "Resume the experiment to get there." : undefined}
          </EmptyState>
        </>
      )}

      {!shown && results.isPending && <Skeleton height={320} />}
    </Page>
  );
}
