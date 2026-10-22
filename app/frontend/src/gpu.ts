import type { Schemas } from "./backend/client";
import type { Tone } from "./components/Badge";

type ComputeStatus = Schemas["ComputeStatusResponse"];
type Session = Schemas["ComputeSession"];
type BackendInfo = Schemas["BackendInfo"];

/** The GPU in one line, for the header chip (docs/notes/frontend-plan.md, 4.2). */
export function gpuSummary(compute: ComputeStatus): { tone: Tone; text: string } {
  const { session, managed, last, backends } = compute;
  if (session) {
    const alwaysOn = isAlwaysOn(backends, session.backend);
    switch (session.status) {
      case "starting":
        return { tone: "active", text: `${alwaysOn ? "Connecting" : "Starting"}: ${session.instance}` };
      case "ready":
        if (session.stop_requested === 1) {
          return { tone: "warn", text: `${alwaysOn ? "Disconnecting" : "Stopping"}: ${session.instance}` };
        }
        if (isReconnecting(session)) return { tone: "warn", text: `Reconnecting: ${session.instance}` };
        return { tone: "ok", text: `${alwaysOn ? "Connected" : "Ready"}: ${session.instance}` };
      case "stopping":
        return { tone: "warn", text: `${alwaysOn ? "Disconnecting" : "Stopping"}: ${session.instance}` };
      default:
        break;
    }
  }
  if (!managed) return { tone: "warn", text: "Mock sim: results aren't predictions" };
  if (last?.status === "failed") return { tone: "bad", text: "GPU failed: open for details" };
  return { tone: "warn", text: "No GPU connected" };
}

/** The connection dropped mid-session (usually the VPN): running jobs wait for it rather than fail (plan 4.7). Read from
 *  the session's message until the API has a structured flag for it (plan, section 13). */
export function isReconnecting(session: Session | null | undefined): boolean {
  if (session?.status !== "ready") return false;
  const message = session.message ?? "";
  return (
    message.includes("isn't answering") ||
    message.startsWith("Reconnecting to the sim server") ||
    message.includes("stopped; starting it again")
  );
}

/** Whether a backend's targets are always on and shared (the GB10): connected and disconnected, never started or stopped. */
export function isAlwaysOn(backends: BackendInfo[], name: Session["backend"]): boolean {
  return backends.find((backend) => backend.name === name)?.always_on ?? false;
}

export type StartStep = { label: string; state: "done" | "current" | "todo"; retry?: string };

// The steps a session goes through while it starts, each recognised by the start of the session's message (plan 4.4).
// A Brev instance boots first; the GB10 is always on, so it only starts the sim server if it isn't running already.
const BOOT = {
  label: "Starting the instance (a few minutes)",
  match: (m: string) => m === "Starting" || /^Starting (?!the sim server)/.test(m),
};
const CONTAINER = {
  label: "Waiting for the instance's Isaac container",
  match: (m: string) => m.startsWith("Waiting for the instance's Isaac container"),
};
const SIM = {
  label: "Starting Isaac Sim and the sim server (about a minute)",
  match: (m: string) => m.startsWith("Starting the sim server") || /^Isaac Sim .* trying again/.test(m),
};
const CONNECT = { label: "Connecting to the sim server", match: (m: string) => m.startsWith("Connecting to the sim server") };

/** The starting steps with the current one marked, from the session's message. An automatic retry of Isaac Sim's start
 *  ("trying again (2 of 3)") is part of a step, not a failure: it comes back as `retry`. */
export function startingSteps(session: Session, alwaysOn: boolean): StartStep[] {
  const steps = alwaysOn ? [SIM, CONNECT] : [BOOT, CONTAINER, SIM, CONNECT];
  const message = session.message ?? "";
  const found = steps.findIndex((step) => step.match(message));
  const current = found < 0 ? 0 : found;
  const retry = /trying again \((\d+) of (\d+)\)/.exec(message);
  return steps.map((step, i) => ({
    label: step.label,
    state: i < current ? "done" : i === current ? "current" : "todo",
    retry:
      i === current && retry
        ? `Retrying: start ${retry[1]} of ${retry[2]}. Isaac Sim fails to start now and then; the app tries again by itself.`
        : undefined,
  }));
}
