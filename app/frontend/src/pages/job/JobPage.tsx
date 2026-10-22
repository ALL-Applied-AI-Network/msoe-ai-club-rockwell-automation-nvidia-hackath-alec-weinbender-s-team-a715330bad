import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { useParams } from "react-router";
import type { Schemas } from "../../backend/client";
import { Banner } from "../../components/Banner";
import { canResume, isActive } from "../../components/Badges";
import { Button, LinkButton } from "../../components/Button";
import { Card } from "../../components/Card";
import { Page } from "../../components/Page";
import { EmptyState, ErrorState, Skeleton } from "../../components/States";
import { mm } from "../../format";
import { useJobEvents } from "../experiments/useJobEvents";
import { jobKey } from "../validation/queries";
import { ClipsSection } from "./clips/ClipsSection";
import { BestFingerSection } from "./finger/BestFingerSection";
import { JobHeader } from "./JobHeader";
import { Progress, SearchCard } from "./Progress";
import { useJobDetail, useRescore, useResults, type Rescore } from "./queries";
import { ResultBanners } from "./sections/Banners";
import { Curves } from "./sections/Curves";
import { Failures } from "./sections/Failures";
import { FinalTest } from "./sections/FinalTest";
import { HeldMaps } from "./sections/HeldMaps";
import { InHand } from "./sections/InHand";
import { Physical } from "./sections/Physical";
import { RescoreBar } from "./sections/RescoreBar";
import { ReviewSection } from "./sections/Review";
import { RunDetails } from "./sections/RunDetails";
import { Summary } from "./sections/Summary";
import { Stopped } from "./Stopped";
import type { ClipPick } from "./types";
import styles from "./JobPage.module.css";

type JobCard = Schemas["JobCard"];

/** #/jobs/:id: one experiment at one address (frontend-plan.md 6.2, 6.3, 7). Live progress while it runs, then the
 *  results, answer first and evidence after. The same sections fill in as the run finishes, so the layout doesn't jump. */
export function JobPage() {
  const { id = "" } = useParams();
  const queryClient = useQueryClient();
  const detail = useJobDetail(id);
  const results = useResults(id);
  const [override, setOverride] = useState<Rescore | null>(null);
  const [resets, setResets] = useState(0); // bumps on Reset, so the re-score bar starts again from the run's values
  const rescore = useRescore(id, override);
  const [picked, setPicked] = useState<ClipPick | null>(null);

  // Follow a running job over its event stream: each card updates the page, and a new round or status refreshes the
  // results (each search's best-so-far curve) and the job.
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
      <Page title="Experiment">
        <ErrorState title="Couldn't load this experiment" message={detail.error.message} onRetry={() => void detail.refetch()} />
      </Page>
    );
  }

  const job = detail.data;
  const status = job.card.status;
  const base = results.data;
  const shown = override && rescore.data ? rescore.data : base;
  const done = Boolean(shown?.summary);

  return (
    <Page>
      <JobHeader job={job} results={base} />

      {isActive(status) && <Progress job={job} results={base} />}
      {canResume(status) && <Stopped card={job.card} />}

      {results.isError && (
        <ErrorState title="Couldn't load the results" message={results.error.message} onRetry={() => void results.refetch()} />
      )}

      {shown && done && base && (
        <div className={styles.sections}>
          <ResultBanners job={job} results={shown} />
          {override && (
            <Banner
              tone="info"
              title="Re-scored: a what-if, not the run's own result"
              action={
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => {
                    setOverride(null);
                    setResets((n) => n + 1);
                  }}
                >
                  Reset
                </Button>
              }
            >
              At σ {mm(override.error?.sigma_mm ?? base.header.error.sigma_mm)}
              {override.task ? `, ${override.task.kind}` : ""}
              {override.task?.offset_tolerance_mm != null ? ` within ${mm(override.task.offset_tolerance_mm)}` : ""}, from the
              stored grasps. Nothing was simulated again.
            </Banner>
          )}
          <Summary results={shown} />
          <RescoreBar
            key={resets}
            error={base.header.error}
            task={base.header.task}
            active={override !== null}
            pending={rescore.isFetching}
            failure={rescore.error?.message}
            onChange={setOverride}
          />
          {shown.curves && <Curves results={shown} />}
          {shown.held_maps.length > 0 && (
            <HeldMaps results={shown} onPick={shown.header.sim_backend === "isaac" ? setPicked : undefined} />
          )}
          {shown.in_hand && shown.header.task.kind !== "drop" && <InHand results={shown} />}
          {shown.failures && <Failures results={shown} />}
          <BestFingerSection jobId={id} results={shown} />
          <ClipsSection jobId={id} results={shown} picked={picked} onPicked={setPicked} />
          {shown.final_table.length > 0 && <FinalTest jobId={id} results={shown} />}
          <Physical jobId={id} results={shown} />
          <ReviewSection jobId={id} experimentId={job.card.experiment_id} review={job.review} />
          <RunDetails jobId={id} results={base} />
        </div>
      )}

      {base && !done && (
        <div className={styles.sections}>
          {canResume(status) && <SearchCard searches={base.run.searches} />}
          <Card title="Results">
            <EmptyState title="Available after the final test">
              The summary, the curves, the held maps, the best finger and its downloads appear here when the final test
              re-checks the top designs.
              {status === "failed" || status === "cancelled" || status === "interrupted" ? " Resume the experiment to get there." : ""}
            </EmptyState>
          </Card>
          <RunDetails jobId={id} results={base} />
        </div>
      )}

      {!base && results.isPending && <Skeleton height={320} />}

      <div>
        <LinkButton variant="ghost" to="/">
          Back to the experiments
        </LinkButton>
      </div>
    </Page>
  );
}
