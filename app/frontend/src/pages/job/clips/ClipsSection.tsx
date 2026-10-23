import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { useCompute } from "../../../backend/queries";
import { Badge } from "../../../components/Badge";
import { Button } from "../../../components/Button";
import { Card } from "../../../components/Card";
import { Segmented } from "../../../components/Segmented";
import { Table } from "../../../components/Table";
import { VideoPair, type PairVideo } from "../../../components/VideoPair";
import { VideoPlayer } from "../../../components/VideoPlayer";
import { dateTime, offset } from "../../../format";
import { designLabel } from "../../../labels";
import { scoredPoses } from "../describe";
import type { ClipPick, Results } from "../types";
import {
  CLIP_STATUS,
  clipUrl,
  findClip,
  storedOutcome,
  suggestions,
  useClips,
  useRecord,
  type Clip,
  type Offset,
} from "./clips";
import styles from "./ClipsSection.module.css";

const VIEWS = [
  { value: "closeup", label: "Close-up of the fingers" },
  { value: "side", label: "Side camera, with the arm" },
] as const;
type View = (typeof VIEWS)[number]["value"];

/** Results, "Watch it in Isaac Sim" (frontend-plan.md 7.5). `picked` is a grasp the user clicked on the held map, to
 *  record; `onPicked(null)` clears it once handled. Real footage of the best design and stock closing on the part at
 *  the same grasp, filmed by the sim server on request and kept with the experiment. */
export function ClipsSection({
  jobId,
  results,
  picked,
  onPicked,
}: {
  jobId: string;
  results: Results;
  picked: ClipPick | null;
  onPicked: (pick: ClipPick | null) => void;
}) {
  const { header } = results;
  const mock = header.sim_backend === "mock";
  const poses = scoredPoses(results);
  const onePose = poses ? `Filmed ${poses[0].label ?? "in the likeliest pose"} only` : undefined; // clips are the primary's
  const finalDone = results.final_table.length > 0 && results.held_maps.length > 0;
  const section = useRef<HTMLElement>(null);
  const [custom, setCustom] = useState<ClipPick | null>(null);
  const [chosen, setChosen] = useState<string>("centre");
  const [view, setView] = useState<View>("closeup");

  // A dot clicked on the held map becomes the grasp to film.
  useEffect(() => {
    if (!picked) return;
    setCustom(picked);
    setChosen("picked");
    section.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    onPicked(null);
  }, [picked, onPicked]);

  const clips = useClips(jobId, !mock && finalDone);
  const record = useRecord(jobId);
  const compute = useCompute();
  const notReady = compute.data?.not_ready_reason;

  const best = results.final_table.find((row) => row.kind === "search" || row.kind === "locked")?.label ?? "D1";
  const lead = custom && chosen === "picked" && custom.design.toUpperCase() !== "STOCK" ? custom.design : best;
  const pair = [lead, "STOCK"];
  const options = suggestions(results, best);
  if (custom) {
    options.push({ key: "picked", label: "Picked on the held map", why: `${designLabel(custom.design)}'s map.`, at: custom.offset });
  }
  const current = options.find((o) => o.key === chosen) ?? options[0];

  if (mock || !finalDone) {
    return (
      <Card title="Watch it in Isaac Sim" subtitle={onePose}>
        <p className={styles.note}>
          {mock
            ? "Needs the Isaac sim. This experiment ran on the mock sim, which films nothing."
            : "Available after the final test."}
        </p>
        <div className={styles.example}>
          <TaskExample kind={header.task.kind} />
        </div>
      </Card>
    );
  }

  const existing = clips.data ?? [];
  // The designs of the pair still to film at the chosen grasp: a failed clip can be asked for again.
  const pending = current
    ? pair.filter((design) => {
        const clip = findClip(existing, design, current.at);
        return !clip || clip.status === "failed";
      })
    : [];

  return (
    <section ref={section} className={styles.anchor}>
      <Card title="Watch it in Isaac Sim" subtitle={onePose}>
        <div className={styles.picker}>
          <h3 className={styles.heading}>Choose a grasp</h3>
          <div className={styles.options} role="radiogroup" aria-label="Grasp to film">
            {options.map((option) => (
              <button
                key={option.key}
                type="button"
                role="radio"
                aria-checked={current?.key === option.key}
                className={styles.option}
                onClick={() => setChosen(option.key)}
              >
                <span className={styles.optionLabel}>{option.label}</span>
                <span className={styles.optionAt}>{offset(option.at.dx, option.at.dy, option.at.yaw_deg)}</span>
                <span className={styles.optionWhy}>
                  {option.why} {outcomeLine(results, pair, option.at)}
                </span>
              </button>
            ))}
          </div>
          <p className={styles.note}>
            Or click a point on the held maps. {designLabel(lead)} and stock are filmed at the same grasp.
          </p>
        </div>

        {current && (
          <div className={styles.recordRow}>
            <Button
              disabled={pending.length === 0 || Boolean(notReady) || record.isPending}
              onClick={() => record.mutate({ designs: pending, at: current.at })}
            >
              {pending.length === 0
                ? "Filmed"
                : `Record ${pending.map(designLabel).join(" and ")} at ${offset(current.at.dx, current.at.dy, current.at.yaw_deg)}`}
            </Button>
            {notReady && (
              <span className={styles.note}>
                {notReady} <Link to="/gpu">Connect a GPU</Link>
              </span>
            )}
            {!notReady && pending.length > 0 && (
              <span className={styles.note}>
                About 12 s a clip. Clips wait behind a running job, so record once it has finished.
              </span>
            )}
          </div>
        )}
        {record.error && <p className={styles.error}>{record.error.message}</p>}

        {current && <Player jobId={jobId} results={results} clips={existing} pair={pair} at={current.at} view={view} />}
        <Segmented label="Camera" options={[...VIEWS]} value={view} onChange={setView} />

        {existing.length > 0 && (
          <Table
            label="Recorded clips"
            rows={existing}
            rowKey={(clip) => String(clip.id)}
            rowTone={(clip) => (clip.status === "failed" ? "bad" : undefined)}
            columns={[
              { key: "design", header: "Design", render: (clip) => designLabel(clip.design), sortValue: (clip) => clip.design },
              {
                key: "offset",
                header: "Grasp",
                render: (clip) => offset(clip.offset.dx, clip.offset.dy, clip.offset.yaw_deg),
              },
              {
                key: "status",
                header: "Status",
                render: (clip) =>
                  clip.status === "failed" ? (
                    <span className={styles.error}>{clip.error ?? "Failed"}</span>
                  ) : (
                    <Badge {...CLIP_STATUS[clip.status]} dot={clip.status === "recording"} />
                  ),
              },
              { key: "outcome", header: "In this clip", render: (clip) => <OutcomeBadge clip={clip} /> },
              { key: "created", header: "Asked for", render: (clip) => dateTime(clip.created), sortValue: (clip) => clip.created },
              {
                key: "show",
                header: "",
                align: "right",
                render: (clip) => (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      setCustom({ design: clip.design, offset: clip.offset });
                      setChosen("picked");
                    }}
                  >
                    Show
                  </Button>
                ),
              },
            ]}
          />
        )}
      </Card>
    </section>
  );
}

/** The pair at one grasp: both videos once both are ready, otherwise where each one is. */
function Player({
  jobId,
  results,
  clips,
  pair,
  at,
  view,
}: {
  jobId: string;
  results: Results;
  clips: Clip[];
  pair: string[];
  at: Offset;
  view: View;
}) {
  const found = pair.map((design) => ({ design, clip: findClip(clips, design, at) }));
  const ready = found.every(({ clip }) => clip?.status === "ready" && clip.views.includes(view));
  if (ready) {
    const [left, right] = found.map(({ design, clip }) => video(jobId, results, design, clip!, view));
    return <VideoPair left={left} right={right} />;
  }
  return (
    <div className={styles.waiting}>
      {found.map(({ design, clip }) => (
        <div key={design} className={styles.slot}>
          <span className={styles.slotDesign}>{designLabel(design)}</span>
          {!clip ? (
            <span className={styles.note}>Not filmed at this grasp yet.</span>
          ) : clip.status === "ready" ? (
            <span className={styles.note}>Ready. It has no {view === "side" ? "side camera" : "close-up"} view.</span>
          ) : clip.status === "failed" ? (
            <span className={styles.error}>{clip.error ?? "Failed"}</span>
          ) : (
            <Badge {...CLIP_STATUS[clip.status]} dot={clip.status === "recording"} />
          )}
        </div>
      ))}
    </div>
  );
}

function video(jobId: string, results: Results, design: string, clip: Clip, view: View): PairVideo {
  const where = offset(clip.offset.dx, clip.offset.dy, clip.offset.yaw_deg);
  const stored = storedOutcome(results, design, clip.offset);
  return {
    src: clipUrl(jobId, clip, view),
    label: `${designLabel(design)} grasping the part at ${where} in Isaac Sim: ${clip.outcome === "held" ? "it holds" : "it drops it"}.`,
    caption: (
      <span className={styles.caption}>
        <span className={styles.captionHead}>
          <strong>{designLabel(design)}</strong>
          <OutcomeBadge clip={clip} />
        </span>
        <span>{where}</span>
        {clip.matches_result === false && stored !== undefined && (
          <span className={styles.differs}>
            The experiment's result here is {stored ? "held" : "missed"}. Near the capture edge about 9% of grasps
            flip between runs, so this happens now and then.
          </span>
        )}
        {clip.result == null && <span>Off the final grid: there's no stored result to compare.</span>}
      </span>
    ),
  };
}

function OutcomeBadge({ clip }: { clip: Clip }) {
  if (!clip.outcome) return <span className={styles.note}>Not yet</span>;
  return clip.outcome === "held" ? <Badge tone="ok" label="Held" /> : <Badge tone="bad" label="Missed" />;
}

/** What the results say happens at a grasp, for each design in the pair: "D1 holds it, stock misses." */
function outcomeLine(results: Results, pair: string[], at: Offset): string {
  const parts = pair
    .map((design) => ({ design, held: storedOutcome(results, design, at) }))
    .filter((p) => p.held !== undefined)
    .map((p) => `${designLabel(p.design)} ${p.held ? "holds" : "misses"}`);
  return parts.length ? `In the results: ${parts.join(", ")}.` : "";
}

/** The task's example video, for experiments with no clips: clearly an example, not this experiment. */
function TaskExample({ kind }: { kind: "drop" | "place" | "insert" }) {
  return (
    <VideoPlayer
      src={`/task-examples/${kind}.mp4`}
      poster={`/task-examples/${kind}.jpg`}
      label={`An example of the pick and ${kind} task in Isaac Sim, with the robot's stock fingers and a 10 mm cube.`}
      caption="Example only: the stock fingers and a 10 mm cube, not this experiment."
    />
  );
}

