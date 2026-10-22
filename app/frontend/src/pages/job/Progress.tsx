import { useEffect, useState } from "react";
import { Link } from "react-router";
import type { Schemas } from "../../backend/client";
import { useCompute, useMeta } from "../../backend/queries";
import { Banner } from "../../components/Banner";
import { Card } from "../../components/Card";
import { SearchProgressChart } from "../../components/charts/SearchProgressChart";
import { ProgressBar } from "../../components/ProgressBar";
import { Stat } from "../../components/Stat";
import { duration, of, percent } from "../../format";
import { isReconnecting } from "../../gpu";
import { methodText } from "./describe";
import type { Results } from "./types";
import styles from "./JobPage.module.css";

type JobDetail = Schemas["JobDetailResponse"];
type SearchRun = Schemas["SearchProgress"];

/** A running experiment (frontend-plan.md 6.2): where it's got to, how long is left, the GPU it runs on, and why a
 *  stalled bar is stalled. The work runs in the background, so the page can be closed and opened again. */
export function Progress({ job, results }: { job: JobDetail; results: Results | undefined }) {
  const compute = useCompute();
  const now = useNow(1000);
  const card = job.card;
  const elapsed = Math.max(0, now / 1000 - card.created);
  const waiting = isReconnecting(compute.data?.session);
  const left = timeLeft(job, elapsed);
  const session = compute.data?.session;
  const gpu = session ? session.instance : compute.data?.managed ? "No GPU connected" : "Mock sim, on this computer";

  return (
    <>
      {waiting && (
        <Banner tone="warn" title="Waiting for the GPU connection">
          The connection to the sim dropped, usually the VPN. The job waits for it and carries on by itself once it's
          back; nothing needs restarting. {session?.message}
        </Banner>
      )}
      <Card
        title="Progress"
        subtitle="It runs in the background on this computer: you can close the page and come back."
        aside={<span className={styles.note}>{card.status === "finalizing" ? "Final test" : `Round ${of(card.round, card.n_rounds)}`}</span>}
      >
        <div className={styles.stats}>
          <Stat label="Designs evaluated" value={of(card.n_done, card.n_total)} />
          <Stat label="Best so far" value={card.best_value == null ? "None yet" : percent(card.best_value)} tone="acc" />
          <Stat label="Elapsed" value={duration(elapsed)} />
          <Stat label="Left, roughly" value={left == null ? "Unknown yet" : duration(left)} />
          <Stat label="Runs on" value={gpu} />
        </div>
        <ProgressBar
          value={card.n_total ? card.n_done / card.n_total : 0}
          label="Designs evaluated"
          tone={waiting ? "warn" : "acc"}
        />
        {card.status === "queued" && <p className={styles.note}>The worker is starting.</p>}
        {card.status === "finalizing" && (
          <p className={styles.note}>
            Final test: the top designs and the baselines, re-tested on the dense grid. The results appear here when it
            finishes.
          </p>
        )}
        {compute.data?.managed && !session && (
          <p className={styles.warn}>
            No GPU is connected, so the next round waits for one. <Link to="/gpu">Connect a GPU</Link>
          </p>
        )}
      </Card>
      {results && <SearchCard searches={results.run.searches} provisional />}
    </>
  );
}

/** Each search's best success so far, against designs evaluated. While the job runs it's provisional. */
export function SearchCard({ searches, provisional = false }: { searches: SearchRun[]; provisional?: boolean }) {
  const meta = useMeta();
  const family = (name: string) => meta.data?.families.find((f) => f.name === name)?.label ?? name;
  const withData = searches.filter((s) => s.best_so_far.length > 0);
  return (
    <Card
      title="Search progress"
      subtitle={
        provisional
          ? "So far, from the 81-point search grid. The final test re-checks the top designs on 321 points and can change their order."
          : "Best success so far against designs evaluated, on the search grid."
      }
    >
      {withData.length === 0 ? (
        <p className={styles.note}>No designs evaluated yet: the first round is running.</p>
      ) : (
        <SearchProgressChart
          searches={withData.map((s) => ({
            key: s.key,
            label: `${family(s.family)}, ${methodText(s.method).toLowerCase()}`,
            bestSoFar: s.best_so_far,
            initial: s.n_initial,
          }))}
          summary={withData
            .map(
              (s) =>
                `${family(s.family)}: best ${s.best == null ? "none yet" : percent(s.best)} after ${s.designs_evaluated} of ${s.budget} designs.`,
            )
            .join(" ")}
          note="Round 0 tries the starting designs; after the marked line, the Bayesian search picks each batch from what it has learnt."
        />
      )}
    </Card>
  );
}

/** Roughly how long is left: from the rate so far once a few designs are done, else from the plan's estimate. */
function timeLeft(job: JobDetail, elapsed: number): number | null {
  const { n_done, n_total } = job.card;
  if (n_done >= n_total) return null;
  if (n_done > 0 && elapsed > 20) return ((n_total - n_done) * elapsed) / n_done;
  const estimate = job.plan.estimate.seconds;
  return estimate == null ? null : Math.max(0, estimate - elapsed);
}

function useNow(ms: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(timer);
  }, [ms]);
  return now;
}
