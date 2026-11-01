import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { api, unwrap, unwrapAs, type Schemas } from "../../../backend/client";
import { useCellProfile, useCompute, useMeta } from "../../../backend/queries";
import { Badge } from "../../../components/Badge";
import { canResume, isActive, JobStatusBadge, SimBadge } from "../../../components/Badges";
import { Banner } from "../../../components/Banner";
import { Button, LinkButton } from "../../../components/Button";
import { Card } from "../../../components/Card";
import { SuccessCurveChart, type CurveSeries } from "../../../components/charts/SuccessCurveChart";
import { ConfirmDialog } from "../../../components/ConfirmDialog";
import { KeyValues } from "../../../components/KeyValues";
import { Notes } from "../../../components/Notes";
import { Page } from "../../../components/Page";
import { ProgressBar } from "../../../components/ProgressBar";
import { Score } from "../../../components/Score";
import { ErrorState, Skeleton } from "../../../components/States";
import { Table, type Column } from "../../../components/Table";
import { dateTime, degrees, mm, of, percent } from "../../../format";
import { FINGER_SOURCES } from "../../../labels";
import { jobKey } from "../../validation/queries";
import { errorText, taskText } from "../describe";
import { useRefresh, type Rescore } from "../queries";
import { RescoreBar } from "../sections/RescoreBar";
import styles from "./EvaluationResults.module.css";

type JobDetail = Schemas["JobDetailResponse"];
type Ranking = Schemas["EvaluationResults"];
type Ranked = Schemas["RankedFinger"];

const CURVE_FINGERS = 3; // the top fingers drawn on the curve, besides the stock fingers

/** An evaluation job: the library's fingers ranked on the part, each at its best grasp, the answer to "can we run this
 *  part with what we have". Live progress while it runs; re-scores at another grasp accuracy or task in the rail. */
export function EvaluationResults({ job }: { job: JobDetail }) {
  const id = job.id;
  const [override, setOverride] = useState<Rescore | null>(null);
  const [resets, setResets] = useState(0);
  const ranking = useQuery({
    queryKey: [...jobKey(id), "ranking"],
    queryFn: () => unwrapAs<Ranking>(api.GET("/api/jobs/{job_id}/ranking", { params: { path: { job_id: id } } })),
  });
  const rescore = useQuery({
    queryKey: [...jobKey(id), "ranking", override],
    queryFn: () =>
      unwrapAs<Ranking>(api.POST("/api/jobs/{job_id}/ranking/rescore", { params: { path: { job_id: id } }, body: override! })),
    enabled: override !== null,
    placeholderData: keepPreviousData,
    staleTime: Infinity,
  });
  const shown = override && rescore.data ? rescore.data : ranking.data;
  const card = job.card;
  const best = shown?.fingers.find((f) => f.best.length > 0);

  const rail = shown ? (
    <>
      <RescoreBar
        key={resets}
        error={shown === rescore.data ? ranking.data!.error : shown.error}
        task={shown === rescore.data ? ranking.data!.task : shown.task}
        active={override !== null}
        pending={rescore.isFetching}
        failure={rescore.error?.message}
        onChange={setOverride}
      />
      {card.status === "done" && (
        <Card title="Not good enough?">
          <p className={styles.text}>
            Design a new finger for this part: a generation job on the same part, cell and grasp accuracy, starting from the
            best grasp of each pose.
          </p>
          <div className={styles.buttons}>
            <LinkButton variant="primary" to={`/new/part?generate=${id}`}>
              Generate a new finger
            </LinkButton>
            {best && best.source !== "stock" && (
              <LinkButton variant="secondary" to={`/new/part?generate=${id}&finger=${best.finger_id}`}>
                Start from {best.code}'s grasp
              </LinkButton>
            )}
          </div>
        </Card>
      )}
      <Card title="Poses covered" subtitle="Each finger's score weighs its best grasp in each">
        <ul className={styles.poses}>
          {shown.poses.map((pose) => (
            <li key={pose.key}>
              <span>{capitalise(pose.label ?? "As in the CAD file")}</span>
              <span className={styles.faint}>
                {percent(pose.weight)} of the score, {pose.grasps.length} {pose.grasps.length === 1 ? "grasp" : "grasps"} tried
              </span>
            </li>
          ))}
        </ul>
      </Card>
    </>
  ) : undefined;

  return (
    <Page header={<Header job={job} ranking={ranking.data} />} rail={rail} stretch={false}>
      {isActive(card.status) && (
        <Card title="Simulating the library" subtitle={`Sim request ${of(card.round, card.n_rounds)}`}>
          <ProgressBar value={card.n_total ? card.n_done / card.n_total : 0} label="Fingers simulated" tone="active" />
          <p className={styles.faint}>
            {of(card.n_done, card.n_total)} finger and grasp pairs simulated. The ranking below fills in as each request finishes.
          </p>
        </Card>
      )}
      {canResume(card.status) && (
        <Banner tone={card.status === "failed" ? "bad" : "warn"} title={card.status === "failed" ? "The evaluation failed" : "The evaluation stopped"}>
          {card.failure ?? "Resume continues after the last finished sim request."}
        </Banner>
      )}
      {ranking.isPending && <Skeleton height={360} />}
      {ranking.isError && <ErrorState title="Couldn't load the ranking" message={ranking.error.message} onRetry={() => void ranking.refetch()} />}
      {shown && (
        <>
          <Notes
            title="What these numbers assume"
            tone={shown.sim_backend === "mock" ? "warn" : "info"}
            notes={shown.warnings.filter((w) => !w.includes("can't grip the part at any grasp")).map(capitalise)}
          />
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
              At a {mm(shown.error.sigma_mm)} grasp error, from the stored grasps. Nothing was simulated again.
            </Banner>
          )}
          <Card
            title={`Fingers ranked at a ${mm(shown.error.sigma_mm)} grasp error`}
            subtitle={shown.final ? "The top fingers and stock re-tested on the dense grid" : "Search grid so far: the final test re-tests the top fingers"}
            aside={<SimBadge backend={shown.sim_backend} />}
            flush
          >
            <RankingTable fingers={shown.fingers} poses={shown.poses.length} />
          </Card>
          {shown.fingers.some((f) => Object.keys(f.curve).length > 0) && <CurveCard ranking={shown} />}
        </>
      )}
    </Page>
  );
}

function RankingTable({ fingers, poses }: { fingers: Ranked[]; poses: number }) {
  const columns: Column<Ranked>[] = [
    { key: "rank", header: "Rank", width: "64px", render: (f) => <span className={styles.rank}>{f.rank}</span> },
    {
      key: "finger",
      header: "Finger",
      width: "30%",
      render: (f) => {
        const ruledOut = f.best.length === 0 ? f.grasps.find((g) => g.reasons.length > 0)?.reasons[0] : undefined;
        return (
          <div className={styles.lines}>
            <span className={styles.finger}>
              <Link to={`/fingers/${f.finger_id}`} className={styles.main} title={f.name}>
                {f.name}
              </Link>
            </span>
            <span className={styles.sub}>
              <code>{f.code}</code> {FINGER_SOURCES[f.source]}
            </span>
            {ruledOut && (
              <span className={styles.bad} title={ruledOut}>
                Can't grip: {ruledOut}
              </span>
            )}
          </div>
        );
      },
    },
    { key: "success", header: "Grasp success", width: "20%", render: (f) => <Score value={f.best.length ? f.success : 0} sub={f.stage === "search" && f.best.length ? "Search grid" : undefined} /> },
    {
      key: "grasp",
      header: poses > 1 ? "Best grasp, first pose" : "Best grasp",
      width: "18%",
      render: (f) => {
        const grasp = f.best[0];
        if (!grasp) return <span className={styles.faint}>None</span>;
        return (
          <div className={styles.lines}>
            <span className={styles.main}>Jaws at {degrees(grasp.angle_deg)}</span>
            <span className={styles.sub}>{grasp.tip_height_mm != null ? `Tips ${mm(grasp.tip_height_mm)} up` : "The cell's own rule"}</span>
          </div>
        );
      },
    },
    {
      key: "radius",
      header: "Holds out to",
      width: "14%",
      render: (f) => (
        <div className={styles.lines}>
          <span className={styles.main}>{f.capture_radius_mm != null ? mm(f.capture_radius_mm) : "None"}</span>
          <span className={styles.sub}>{f.n_grasps} grasps</span>
        </div>
      ),
    },
    {
      key: "robot",
      header: "On the robot",
      width: "18%",
      render: (f) =>
        f.real_trials > 0 && f.measured_success != null ? (
          <div className={styles.lines}>
            <span className={styles.main}>{percent(f.measured_success)}</span>
            <span className={styles.sub}>{f.real_trials} real trials</span>
          </div>
        ) : (
          <span className={styles.faint}>Not tested</span>
        ),
    },
  ];
  return <Table label="Fingers ranked" columns={columns} rows={fingers} rowKey={(f) => f.finger_id} fixed />;
}

/** Success against grasp error for the top fingers and the stock fingers: how much accuracy each needs. */
function CurveCard({ ranking }: { ranking: Ranking }) {
  const top = ranking.fingers.filter((f) => f.source !== "stock" && f.best.length > 0).slice(0, CURVE_FINGERS);
  const stock = ranking.fingers.find((f) => f.source === "stock");
  const toPoints = (f: Ranked) =>
    Object.entries(f.curve)
      .map(([sigma, success]) => ({ sigma: Number(sigma), success }))
      .sort((a, b) => a.sigma - b.sigma);
  const series: CurveSeries[] = [
    ...top.map((f, i): CurveSeries => ({ key: f.finger_id, label: f.code, points: toPoints(f), color: i === 0 ? "acc" : "faint", shape: i === 0 ? "dot" : "ring", emphasis: i === 0 })),
    ...(stock ? [{ key: stock.finger_id, label: stock.code, points: toPoints(stock), color: "baseline" as const, shape: "square" as const, dashed: true }] : []),
  ];
  const target = ranking.error.sigma_mm;
  return (
    <Card title="Success against grasp error" subtitle={`The cell's ${mm(target)} marked. The leading finger is the heavy line.`}>
      <SuccessCurveChart
        series={series}
        target={target}
        summary={`Predicted success of the top fingers and the stock fingers against grasp error from 0.5 to 5 mm.${
          top[0] ? ` ${top[0].code} holds ${percent(top[0].success)} at ${mm(target)}.` : ""
        }`}
      />
    </Card>
  );
}

/** The evaluation's name and ID, its badges and settings, and what can be done with it. */
function Header({ job, ranking }: { job: JobDetail; ranking: Ranking | undefined }) {
  const meta = useMeta();
  const compute = useCompute();
  const cell = useCellProfile(job.cell_profile_id);
  const refresh = useRefresh(job.id);
  const card = job.card;
  const active = isActive(card.status);
  const notReady = compute.data?.not_ready_reason;
  const [confirming, setConfirming] = useState(false);
  const cancel = useMutation({
    mutationFn: () => unwrap(api.POST("/api/jobs/{job_id}/cancel", { params: { path: { job_id: job.id } } })),
    onSuccess: () => setConfirming(false),
    onSettled: refresh,
  });
  const resume = useMutation({
    mutationFn: () => unwrap(api.POST("/api/jobs/{job_id}/resume", { params: { path: { job_id: job.id } } })),
    onSettled: refresh,
  });

  return (
    <header className={styles.header}>
      <div className={styles.titleRow}>
        <h1 className={styles.title}>
          {card.name}
          <code className={styles.id}>{card.experiment_id}</code>
        </h1>
        <div className={styles.buttons}>
          {active && (
            <Button variant="danger" onClick={() => setConfirming(true)}>
              Cancel
            </Button>
          )}
          {canResume(card.status) && (
            <Button variant="secondary" disabled={Boolean(notReady) || resume.isPending} title={notReady ?? undefined} onClick={() => resume.mutate()}>
              Resume
            </Button>
          )}
          <LinkButton variant="secondary" to={`/evaluate?from=${job.id}`}>
            Evaluate again
          </LinkButton>
        </div>
      </div>
      <div className={styles.badges}>
        <Badge tone="neutral" label="Finger evaluation" />
        <JobStatusBadge status={card.status} />
        <SimBadge backend={card.sim_backend} />
      </div>
      <KeyValues
        inline
        items={[
          { label: "Part", value: card.part_name ?? "Unknown part" },
          ...(ranking ? [{ label: "Grasp accuracy", value: errorText(ranking.error) }, { label: "Task", value: taskText(ranking.task, meta.data) }] : []),
          { label: "Cell", value: cell.data ? `${cell.data.name}, version ${cell.data.version}` : "Loading" },
          { label: card.finished ? "Finished" : "Started", value: dateTime(card.finished ?? card.created) },
        ]}
      />
      {resume.error && <p className={styles.bad}>{resume.error.message}</p>}
      <ConfirmDialog
        open={confirming && active}
        title={`Cancel ${card.experiment_id}?`}
        confirmLabel="Cancel the evaluation"
        cancelLabel="Keep running"
        danger
        pending={cancel.isPending}
        error={cancel.error?.message}
        onConfirm={() => cancel.mutate()}
        onClose={() => setConfirming(false)}
      >
        It stops after the current sim request. Everything done so far is kept, and Resume continues from there.
      </ConfirmDialog>
    </header>
  );
}

function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}
