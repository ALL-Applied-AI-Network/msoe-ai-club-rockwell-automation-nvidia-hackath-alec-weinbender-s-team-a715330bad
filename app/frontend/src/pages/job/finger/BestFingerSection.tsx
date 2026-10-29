import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { api, unwrapAs, type Schemas } from "../../../backend/client";
import { Badge } from "../../../components/Badge";
import { Card } from "../../../components/Card";
import { CopyButton } from "../../../components/CopyButton";
import { DownloadButton } from "../../../components/DownloadButton";
import { FingerViewer, type FingerShape } from "../../../components/FingerViewer";
import { KeyValues } from "../../../components/KeyValues";
import { Segmented } from "../../../components/Segmented";
import { ErrorState, Skeleton } from "../../../components/States";
import { CAVEATS } from "../../../caveats";
import { paramValue } from "../../../format";
import { designLabel, paramLabel } from "../../../labels";
import type { Results } from "../types";
import styles from "./BestFingerSection.module.css";

type FingerView = Schemas["FingerPreview"];
type ChecksResponse = Schemas["ChecksResponse"];
type VPadParams = Schemas["VPadParams"];

/** Results, "Best finger" (frontend-plan.md 7.3): the mirrored pair on the part with the jaws closed, the design's
 *  parameters, the grasp pose for the robot program, and the files to print. Any final design can be chosen; the stock
 *  fingers have no files of ours, so they aren't offered. */
export function BestFingerSection({ jobId, results }: { jobId: string; results: Results }) {
  const designs = results.final_table.filter((row) => row.kind !== "stock");
  const [chosen, setChosen] = useState(results.best_finger?.label ?? designs[0]?.label ?? "");
  const [pose, setPose] = useState<string | null>(null);
  if (designs.length === 0) return null;
  const label = designs.some((d) => d.label === chosen) ? chosen : designs[0].label;
  const row = designs.find((d) => d.label === label)!;
  const poses = row.poses && row.poses.length > 1 ? row.poses : null; // the same finger, regripped in each pose
  const shownPose = poses?.find((p) => p.key === pose)?.key ?? poses?.[0].key ?? null;
  const base = `/api/jobs/${encodeURIComponent(jobId)}/designs/${encodeURIComponent(label)}`;

  return (
    <Card
      title="Best finger"
      subtitle="The pair to print, and the grasp pose for the robot program."
      aside={
        designs.length > 1 && (
          <Segmented
            label="Design"
            value={label}
            onChange={setChosen}
            options={designs.map((d) => ({ value: d.label, label: designLabel(d.label) }))}
          />
        )
      }
    >
      {results.header.sim_backend === "mock" && <p className={styles.caveat}>{CAVEATS.mock} The geometry is real CAD.</p>}
      <div className={styles.layout}>
        <div className={styles.pair}>
          {poses && (
            <Segmented
              label="Resting pose"
              value={shownPose!}
              onChange={setPose}
              options={poses.map((p) => ({ value: p.key, label: capitalise(p.label ?? "unnamed pose") }))}
            />
          )}
          <PairView jobId={jobId} label={label} pose={shownPose} />
        </div>
        <div className={styles.side}>
          <section className={styles.block}>
            <h3 className={styles.heading}>
              {designLabel(label)}
              {label === results.best_finger?.label && <Badge tone="ok" label="Best at the target error" />}
            </h3>
            {row.params ? <ParamList params={row.params} /> : <p className={styles.note}>The imprint: a carved copy of the part.</p>}
          </section>
          <GraspPose base={base} />
          <Downloads jobId={jobId} base={base} label={label} />
        </div>
      </div>
    </Card>
  );
}

/** Both fingers, left and its mirror, closed on the part. */
function PairView({ jobId, label, pose }: { jobId: string; label: string; pose: string | null }) {
  const finger = useQuery({
    queryKey: ["job", jobId, "finger", label, pose],
    queryFn: () =>
      unwrapAs<FingerView>(
        api.GET("/api/jobs/{job_id}/finger", {
          params: { path: { job_id: jobId }, query: { design: label, ...(pose ? { pose } : {}) } },
        }),
      ),
    staleTime: Infinity,
  });
  const fingers: FingerShape[] = useMemo(
    () =>
      finger.data
        ? [
            { key: "left", pieces: finger.data.finger.pieces, tone: "finger" },
            { key: "right", pieces: finger.data.right, tone: "finger" },
          ]
        : [],
    [finger.data],
  );
  if (finger.isPending) return <Skeleton height={380} />;
  if (finger.isError) return <ErrorState title="Couldn't load the 3D view" message={finger.error.message} onRetry={() => void finger.refetch()} />;
  return (
    <FingerViewer
      part={finger.data.part}
      fingers={fingers}
      label={`${designLabel(label)}: the left finger and its mirror closed on the part${finger.data.pose_label ? `, ${finger.data.pose_label}` : ""}`}
      height={380}
      frameKey={`${label}-${pose ?? ""}`}
    />
  );
}

function ParamList({ params }: { params: VPadParams }) {
  const entries = Object.entries(params).filter(([name]) => name !== "family") as [string, number][];
  return (
    <KeyValues
      items={entries.map(([name, value]) => ({ label: paramLabel(name), value: paramValue(value, name.endsWith("_deg") ? "deg" : "mm") }))}
    />
  );
}

/** The grasp pose, as text for the robot program and as JSON, each copyable. */
function GraspPose({ base }: { base: string }) {
  const [format, setFormat] = useState<"text" | "json">("text");
  const pose = useQuery({
    queryKey: ["grasp-pose", base, format],
    queryFn: async () => {
      const response = await fetch(`${base}/grasp-pose?format=${format}`);
      if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
      return format === "json" ? JSON.stringify(await response.json(), null, 2) : await response.text();
    },
    staleTime: Infinity,
  });
  return (
    <section className={styles.block}>
      <div className={styles.row}>
        <h3 className={styles.heading}>Grasp pose</h3>
        <Segmented
          label="Format"
          value={format}
          onChange={setFormat}
          options={[
            { value: "text", label: "Text" },
            { value: "json", label: "JSON" },
          ]}
        />
        {pose.data && <CopyButton text={pose.data} label={format === "json" ? "Copy the JSON" : "Copy the text"} />}
      </div>
      {pose.isError && <p className={styles.error}>{pose.error.message}</p>}
      <pre className={styles.code}>{pose.data ?? "Loading"}</pre>
    </section>
  );
}

/** The files to print, and the export checks that guard them. */
function Downloads({ jobId, base, label }: { jobId: string; base: string; label: string }) {
  const checks = useQuery({
    queryKey: ["job", jobId, "checks", label],
    queryFn: () =>
      unwrapAs<ChecksResponse>(
        api.GET("/api/jobs/{job_id}/designs/{label}/checks", { params: { path: { job_id: jobId, label } } }),
      ),
    staleTime: 60_000,
  });
  const checksUrl = `${base}/checks`;
  return (
    <section className={styles.block}>
      <h3 className={styles.heading}>Files for {designLabel(label)}</h3>
      {checks.data?.blocked && (
        <p className={styles.error}>An export check failed, so these files are blocked until it's fixed: see the checks below.</p>
      )}
      <div className={styles.downloads}>
        <DownloadButton href={`${base}/cad?format=step`} label="STEP of the pair" checksUrl={checksUrl} />
        <DownloadButton href={`${base}/cad?format=stl&side=L`} label="STL, left" checksUrl={checksUrl} />
        <DownloadButton href={`${base}/cad?format=stl&side=R`} label="STL, right" checksUrl={checksUrl} />
        <DownloadButton href={`${base}/print-sheet.pdf`} label="Print sheet (PDF)" checksUrl={checksUrl} />
      </div>
      {checks.data && <Checks checks={checks.data.checks} />}
    </section>
  );
}

type Check = ChecksResponse["checks"][number];

/** Failed checks stay in view; the passed ones fold into a "Passed 4/5" line that opens to list them. */
function Checks({ checks }: { checks: Check[] }) {
  const passed = checks.filter((check) => check.ok);
  const failed = checks.filter((check) => !check.ok);
  return (
    <>
      {failed.length > 0 && (
        <ul className={styles.checks}>
          {failed.map((check) => (
            <CheckItem key={check.name} check={check} />
          ))}
        </ul>
      )}
      {passed.length > 0 && (
        <details className={styles.passed}>
          <summary className={styles.passedSummary}>
            <Badge tone="ok" label={`Passed ${passed.length}/${checks.length}`} />
            <span className={styles.chevron} aria-hidden="true" />
          </summary>
          <ul className={styles.checks}>
            {passed.map((check) => (
              <CheckItem key={check.name} check={check} />
            ))}
          </ul>
        </details>
      )}
    </>
  );
}

function CheckItem({ check }: { check: Check }) {
  return (
    <li className={styles.check}>
      <Badge
        tone={check.ok ? "ok" : check.blocking ? "bad" : "warn"}
        label={check.ok ? "Passed" : check.blocking ? "Failed" : "Failed, not blocking"}
      />
      <span>
        <strong className={styles.checkName}>{capitalise(check.name)}</strong>
        <span className={styles.note}>{check.detail}</span>
      </span>
    </li>
  );
}

function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}
