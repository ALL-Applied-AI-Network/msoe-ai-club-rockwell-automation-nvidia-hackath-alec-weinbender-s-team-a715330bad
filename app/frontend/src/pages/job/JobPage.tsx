import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { useParams } from "react-router";
import type { Schemas } from "../../backend/client";
import { Banner } from "../../components/Banner";
import { canResume, isActive } from "../../components/Badges";
import { Button, LinkButton } from "../../components/Button";
import { Page } from "../../components/Page";
import { EmptyState, ErrorState, Skeleton } from "../../components/States";
import { mm } from "../../format";
import { useJobEvents } from "../experiments/useJobEvents";
import { jobKey } from "../validation/queries";
import { ClipsSection } from "./clips/ClipsSection";
import { BestFingerSection } from "./finger/BestFingerSection";
import { JobHeader } from "./JobHeader";
import { JobRail, type RailSection } from "./JobRail";
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
import type { ClipPick, Results } from "./types";
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
        <div className={styles.withRail}>
          <JobRail sections={railSections(shown)} validationTo={`/jobs/${id}/validation`} />
          <div className={styles.sections}>
            <div id="job-result" className={styles.group}>
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
            </div>
            {hasSearch(shown) && (
              <div id="job-search" className={styles.group}>
                {shown.curves && <Curves results={shown} />}
                {shown.held_maps.length > 0 && (
                  <HeldMaps results={shown} onPick={shown.header.sim_backend === "isaac" ? setPicked : undefined} />
                )}
                {shown.in_hand && shown.header.task.kind !== "drop" && <InHand results={shown} />}
                {shown.failures && <Failures results={shown} />}
              </div>
            )}
            <div id="job-finger" className={styles.group}>
              <BestFingerSection jobId={id} results={shown} />
              <ClipsSection jobId={id} results={shown} picked={picked} onPicked={setPicked} />
            </div>
            <div id="job-test" className={styles.group}>
              {shown.final_table.length > 0 && <FinalTest jobId={id} results={shown} />}
              <Physical jobId={id} results={shown} />
              <ReviewSection jobId={id} experimentId={job.card.experiment_id} review={job.review} />
            </div>
            <div id="job-details" className={styles.group}>
              <RunDetails jobId={id} results={base} />
            </div>
          </div>
        </div>
      )}

      {base && !done && (
        <div className={styles.sections}>
          {canResume(status) && <SearchCard searches={base.run.searches} />}
          <EmptyState title="Results appear after the final test">
            {canResume(status) ? "Resume the experiment to get there." : undefined}
          </EmptyState>
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

const hasSearch = (r: Results) =>
  Boolean(r.curves) || r.held_maps.length > 0 || Boolean(r.in_hand && r.header.task.kind !== "drop") || Boolean(r.failures);

/** The side list's entries, in page order: only the groups this experiment has. */
function railSections(r: Results): RailSection[] {
  return [
    { id: "job-result", label: "Result" },
    ...(hasSearch(r) ? [{ id: "job-search", label: "Search" }] : []),
    { id: "job-finger", label: "Finger" },
    { id: "job-test", label: "Test" },
    { id: "job-details", label: "Details" },
  ];
}
