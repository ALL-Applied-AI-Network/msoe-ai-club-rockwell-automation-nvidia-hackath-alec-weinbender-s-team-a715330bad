import { useState } from "react";
import type { Schemas } from "../../backend/client";
import { Badge, type Tone } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Card } from "../../components/Card";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { HelpCard } from "../../components/HelpCard";
import { KeyValues, type KeyValue } from "../../components/KeyValues";
import { clockTime, count, duration, minutes } from "../../format";
import { isAlwaysOn, isReconnecting, startingSteps } from "../../gpu";
import { gpuHelp } from "../../gpuHelp";
import { useComputeActions, useNow } from "./queries";
import styles from "./GpuPage.module.css";

type Compute = Schemas["ComputeStatusResponse"];
type Session = Schemas["ComputeSession"];
type Instance = Schemas["ComputeInstance"];

/** The session that's starting, ready or stopping: what it is, how long it's been up, and the button that ends it. */
export function CurrentSession({ compute, session, target }: { compute: Compute; session: Session; target?: Instance }) {
  const alwaysOn = isAlwaysOn(compute.backends, session.backend);
  const backendLabel = compute.backends.find((b) => b.name === session.backend)?.label ?? session.backend;
  const now = useNow();
  const { stop } = useComputeActions();
  const [confirming, setConfirming] = useState(false);
  const reconnecting = isReconnecting(session);
  const badge = sessionBadge(session, alwaysOn, reconnecting);

  const facts: KeyValue[] = [
    { label: "Requested", value: clockTime(session.requested) },
    session.status === "starting"
      ? { label: alwaysOn ? "Connecting for" : "Starting for", value: duration(now - session.requested) }
      : session.ready_at
        ? { label: alwaysOn ? "Connected for" : "Up for", value: duration(now - session.ready_at) }
        : { label: "Ready", value: "Not yet" },
  ];
  if (target?.gpu) facts.push({ label: "GPU", value: target.gpu });
  if (target?.other_gpu_processes != null) {
    facts.push({
      label: `On ${session.instance} right now`,
      value: count(target.other_gpu_processes, "other GPU process", "other GPU processes"),
    });
  }
  if (!alwaysOn) {
    facts.push({
      label: "Stops by itself",
      value: compute.auto_stop_minutes > 0 ? `After ${minutes(compute.auto_stop_minutes)} idle` : "Never",
    });
  }

  const ending = session.status === "stopping" || session.stop_requested === 1;
  return (
    <Card
      title={session.instance}
      subtitle={backendLabel}
      aside={
        <>
          <Badge {...badge} dot={badge.tone === "active" || badge.tone === "ok"} />
          {alwaysOn ? (
            <Button variant="secondary" size="sm" disabled={ending || stop.isPending} onClick={() => stop.mutate()}>
              Disconnect
            </Button>
          ) : (
            <Button variant="danger" size="sm" disabled={ending || stop.isPending} onClick={() => setConfirming(true)}>
              Stop the GPU
            </Button>
          )}
        </>
      }
    >
      <KeyValues items={facts} inline />
      {session.message && !reconnecting && <p className={styles.message}>{session.message}</p>}
      {session.status === "starting" && <StartingSteps session={session} alwaysOn={alwaysOn} />}
      {reconnecting && session.message && (
        <HelpCard tone="warn" message={session.message} {...helpProps(session.message)} />
      )}
      {target?.other_gpu_processes ? (
        <p className={styles.note}>Other work on this GPU may slow the sim.</p>
      ) : null}
      {stop.error && <p className={styles.error}>{stop.error.message}</p>}
      <ConfirmDialog
        open={confirming && !ending}
        title={`Stop ${session.instance}?`}
        confirmLabel="Stop the GPU"
        cancelLabel="Keep it running"
        danger
        pending={stop.isPending}
        error={stop.error?.message}
        onConfirm={() => stop.mutate(undefined, { onSuccess: () => setConfirming(false) })}
        onClose={() => setConfirming(false)}
      >
        The instance stops using credits. Running jobs wait and carry on once a GPU is ready again. Starting it again
        takes about 4 minutes.
      </ConfirmDialog>
    </Card>
  );
}

/** The steps a starting session goes through, the current one marked (plan 4.4). A retry is shown as a retry, never in
 *  red: Isaac Sim fails about one start in four on the GB10, and the app tries again by itself. */
function StartingSteps({ session, alwaysOn }: { session: Session; alwaysOn: boolean }) {
  const steps = startingSteps(session, alwaysOn);
  return (
    <ol className={styles.steps} aria-label="Starting steps">
      {steps.map((step) => (
        <li key={step.label} className={styles[step.state]} aria-current={step.state === "current" ? "step" : undefined}>
          <span className={styles.marker} aria-hidden="true" />
          <div>
            <span className={styles.stepLabel}>{step.label}</span>
            {step.state === "done" && <span className={styles.stepState}>Done</span>}
            {step.retry && (
              <div className={styles.retry}>
                <Badge tone="warn" label="Retrying" />
                <span>{step.retry}</span>
              </div>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}

function sessionBadge(session: Session, alwaysOn: boolean, reconnecting: boolean): { tone: Tone; label: string } {
  if (session.stop_requested === 1 && (session.status === "ready" || session.status === "starting")) {
    return { tone: "warn", label: alwaysOn ? "Disconnecting" : "Stopping" }; // asked to stop, not yet acted on
  }
  if (reconnecting) return { tone: "warn", label: "Reconnecting" };
  switch (session.status) {
    case "starting":
      return { tone: "active", label: alwaysOn ? "Connecting" : "Starting" };
    case "ready":
      return { tone: "ok", label: alwaysOn ? "Connected" : "Ready" };
    case "stopping":
      return { tone: "warn", label: alwaysOn ? "Disconnecting" : "Stopping" };
    case "failed":
      return { tone: "bad", label: "Failed" };
    default:
      return { tone: "neutral", label: alwaysOn ? "Disconnected" : "Stopped" };
  }
}

/** A HelpCard's text for a compute error message. */
export function helpProps(message: string) {
  const help = gpuHelp(message);
  return {
    meaning: help.meaning,
    fix: help.fix,
    reference: help.setup ? `SETUP.md, "${help.setup}"` : undefined,
  };
}
