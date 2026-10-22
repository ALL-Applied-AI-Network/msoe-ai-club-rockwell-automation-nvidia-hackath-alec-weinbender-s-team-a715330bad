import type { Schemas } from "../backend/client";
import { CAVEATS } from "../caveats";
import { Badge, type Tone } from "./Badge";

type JobStatus = Schemas["JobCard"]["status"];
type PhysicalStatus = Schemas["JobCard"]["physical_badge"];

const JOB_STATUS: Record<JobStatus, { tone: Tone; label: string; title: string }> = {
  queued: { tone: "neutral", label: "Queued", title: "The worker is starting." },
  running: { tone: "active", label: "Running", title: "Searching finger designs." },
  finalizing: {
    tone: "active",
    label: "Final test",
    title: "The top designs and the baselines, re-tested on the dense grid.",
  },
  done: { tone: "ok", label: "Done", title: "Finished: results are ready." },
  failed: { tone: "bad", label: "Failed", title: "Stopped by an error. Resume continues after the last finished round." },
  cancelled: { tone: "neutral", label: "Cancelled", title: "Resume continues from its last round." },
  interrupted: {
    tone: "warn",
    label: "Interrupted",
    title: "The worker stopped, for example the laptop slept or restarted. Resume continues.",
  },
};

const PHYSICAL: Record<PhysicalStatus, { tone: Tone; label: string }> = {
  none: { tone: "neutral", label: "No physical trials" },
  in_progress: { tone: "active", label: "Physical trials in progress" },
  validated: { tone: "ok", label: "Validated on the robot" },
};

/** A job's status: the same badge on cards, the experiment page and every list. */
export function JobStatusBadge({ status }: { status: JobStatus }) {
  const { tone, label, title } = JOB_STATUS[status];
  return <Badge tone={tone} label={label} title={title} dot={tone === "active"} />;
}

/** Which simulator made a result. Every result carries it: mock results are never predictions. */
export function SimBadge({ backend }: { backend: "mock" | "isaac" }) {
  return backend === "mock" ? (
    <Badge tone="warn" label="Mock sim" title={CAVEATS.mock} />
  ) : (
    <Badge tone="ok" label="Isaac Sim" title="Simulated in the Isaac Sim digital twin." />
  );
}

/** How far an experiment's printed fingers have got on the real robot. */
export function PhysicalBadge({ status }: { status: PhysicalStatus }) {
  return <Badge {...PHYSICAL[status]} />;
}

export function isActive(status: JobStatus): boolean {
  return status === "queued" || status === "running" || status === "finalizing";
}

export function canResume(status: JobStatus): boolean {
  return status === "failed" || status === "cancelled" || status === "interrupted";
}
