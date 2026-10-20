import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, unwrap, type Schemas } from "../backend/client";
import { clockTime, count, duration, minutes } from "../format";
import { Button } from "./Button";
import { Card } from "./Card";
import { Select } from "./Select";
import { StatusBadge, type Tone } from "./StatusBadge";
import styles from "./GpuPanel.module.css";

type Session = Schemas["ComputeSession"];
type Instance = Schemas["ComputeInstance"];
type BackendInfo = Schemas["BackendInfo"];

const SESSION_BADGE: Record<Session["status"], { tone: Tone; label: string }> = {
  starting: { tone: "active", label: "Starting" },
  ready: { tone: "ok", label: "Ready" },
  stopping: { tone: "warn", label: "Stopping" },
  stopped: { tone: "neutral", label: "Stopped" },
  failed: { tone: "bad", label: "Failed" },
};
const ALWAYS_ON_BADGE: Partial<Record<Session["status"], { tone: Tone; label: string }>> = {
  starting: { tone: "active", label: "Connecting" },
  ready: { tone: "ok", label: "Connected" },
  stopping: { tone: "warn", label: "Disconnecting" },
  stopped: { tone: "neutral", label: "Disconnected" },
};
const ENDED: Record<NonNullable<Session["stop_reason"]>, string> = {
  user: "ended from the app",
  idle: "stopped after the idle time",
  external: "stopped outside the app",
  failed: "failed",
};

/** The GPU the sim runs on. Brev instances are started and stopped here (and stop by themselves when idle); the MSOE
 *  GB10 is always on and shared, so it's connected and disconnected, and its sim server keeps running for teammates.
 *  One target at a time. New Brev instances are created in the Brev console, never here. */
export function GpuPanel() {
  const queryClient = useQueryClient();
  const status = useQuery({
    queryKey: ["compute"],
    queryFn: () => unwrap(api.GET("/api/compute")),
    refetchInterval: (query) => (query.state.data?.session ? 3_000 : 15_000),
  });
  const connectedShared = status.data?.session ? isAlwaysOn(status.data.backends, status.data.session.backend) : false;
  const targets = useQuery({
    queryKey: ["compute", "instances"],
    queryFn: () => unwrap(api.GET("/api/compute/instances")),
    retry: false,
    refetchInterval: connectedShared ? 60_000 : false, // the shared GB10's load, while connected to it
  });
  const [chosen, setChosen] = useState("");
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["compute"] });
  const start = useMutation({
    mutationFn: (target: Instance) =>
      unwrap(api.POST("/api/compute/start", { body: { backend: target.backend, instance: target.name } })),
    onSettled: refresh,
  });
  const stop = useMutation({ mutationFn: () => unwrap(api.POST("/api/compute/stop")), onSettled: refresh });

  if (status.isPending) {
    return (
      <Card title="GPU">
        <p className={styles.note}>Loading the GPU status</p>
      </Card>
    );
  }
  if (status.isError) {
    return (
      <Card title="GPU">
        <p className={styles.error}>{status.error.message}</p>
      </Card>
    );
  }

  const { backends, session, last, auto_stop_minutes, not_ready_reason } = status.data;
  const label = (name: Session["backend"]) => backends.find((b) => b.name === name)?.label ?? name;
  const instances = targets.data?.instances ?? [];
  const selected = instances.find((instance) => key(instance) === chosen);
  const busy = start.isPending || stop.isPending;
  const sessionAlwaysOn = session ? isAlwaysOn(backends, session.backend) : false;
  const sessionTarget = session && instances.find((i) => i.backend === session.backend && i.name === session.instance);
  const actionError = start.error ?? stop.error;

  return (
    <Card
      title="GPU"
      aside={
        <span className={styles.status}>
          {backends.map((backend) => (
            <StatusBadge key={backend.name} tone={backend.name === "mock" ? "warn" : "neutral"} label={backend.label} />
          ))}
        </span>
      }
    >
      <div className={styles.body}>
        {session ? (
          <ActiveSession
            session={session}
            alwaysOn={sessionAlwaysOn}
            backendLabel={label(session.backend)}
            otherProcesses={sessionTarget?.other_gpu_processes}
          />
        ) : (
          <NoSession last={last} reason={not_ready_reason} />
        )}

        {session ? (
          <div className={styles.controls}>
            <Button variant="secondary" disabled={busy || session.stop_requested === 1} onClick={() => stop.mutate()}>
              {sessionAlwaysOn ? "Disconnect" : "Stop the GPU"}
            </Button>
          </div>
        ) : (
          <div className={styles.controls}>
            <div className={styles.grow}>
              <Select
                label="Target"
                placeholder={targets.isPending ? "Loading targets" : "Choose a target"}
                options={instances.map((instance) => ({ value: key(instance), label: targetLabel(instance, label(instance.backend)) }))}
                value={chosen}
                onChange={(event) => setChosen(event.target.value)}
              />
            </div>
            <Button disabled={!selected || busy} onClick={() => selected && start.mutate(selected)}>
              {selected?.always_on ? "Connect" : "Start the GPU"}
            </Button>
            <Button variant="secondary" disabled={targets.isFetching} onClick={() => targets.refetch()}>
              Refresh the list
            </Button>
          </div>
        )}

        {targets.isError && <p className={styles.error}>{targets.error.message}</p>}
        {targets.data?.errors.map((error) => (
          <p key={error.backend} className={styles.error}>
            {label(error.backend)}: {error.message}
          </p>
        ))}
        {actionError && <p className={styles.error}>{actionError.message}</p>}
        <Notes backends={backends} autoStopMinutes={auto_stop_minutes} />
      </div>
    </Card>
  );
}

function ActiveSession({
  session,
  alwaysOn,
  backendLabel,
  otherProcesses,
}: {
  session: Session;
  alwaysOn: boolean;
  backendLabel: string;
  otherProcesses: number | null | undefined; // the shared GB10's GPU processes besides our sim server
}) {
  const upFor = session.ready_at ? duration(Date.now() / 1000 - session.ready_at) : null;
  const badge = (alwaysOn && ALWAYS_ON_BADGE[session.status]) || SESSION_BADGE[session.status];
  return (
    <>
      <div className={styles.status}>
        <span className={styles.instance}>{session.instance}</span>
        <StatusBadge tone="neutral" label={backendLabel} />
        <StatusBadge {...badge} />
      </div>
      {session.message && <p className={styles.note}>{session.message}</p>}
      {upFor && <p className={styles.note}>{alwaysOn ? "Connected for" : "Up for"} {upFor}</p>}
      {otherProcesses != null && (
        <p className={styles.note}>
          On {session.instance} right now: {otherGpuProcesses(otherProcesses)}
          {otherProcesses > 0 ? ", another team's or a teammate's, so the sim may run slower" : ""}
        </p>
      )}
    </>
  );
}

function NoSession({ last, reason }: { last: Session | null | undefined; reason: string | null | undefined }) {
  return (
    <>
      {reason && <p className={styles.note}>{reason}</p>}
      {last && last.stopped_at && (
        <p className={last.status === "failed" ? styles.error : styles.note}>
          Last session: {last.instance}, {last.stop_reason ? ENDED[last.stop_reason] : last.status} at {clockTime(last.stopped_at)}
          {last.status === "failed" && last.message ? `: ${last.message}` : ""}
        </p>
      )}
    </>
  );
}

function Notes({ backends, autoStopMinutes }: { backends: BackendInfo[]; autoStopMinutes: number }) {
  const has = (name: BackendInfo["name"]) => backends.some((backend) => backend.name === name);
  return (
    <>
      {has("brev") && (
        <p className={styles.note}>
          {autoStopMinutes > 0
            ? `A Brev instance stops by itself after ${minutes(autoStopMinutes)} without a job or prediction.`
            : "Auto-stop is off: stop the Brev instance when you are done."}{" "}
          New instances are created in the Brev console.
        </p>
      )}
      {has("gb10") && (
        <p className={styles.note}>
          The MSOE GB10 is always on and shared with other teams: it needs the MSOE VPN, and disconnecting leaves its sim
          server running for your teammates.
        </p>
      )}
      {has("mock") && <p className={styles.note}>Mock targets are made up, for working on the app offline.</p>}
    </>
  );
}

function isAlwaysOn(backends: BackendInfo[], name: Session["backend"]): boolean {
  return backends.find((backend) => backend.name === name)?.always_on ?? false;
}

function key(instance: Instance): string {
  return `${instance.backend}/${instance.name}`;
}

function targetLabel(instance: Instance, backendLabel: string): string {
  const machine = instance.gpu ?? instance.instance_type ?? "unknown machine";
  const others = instance.other_gpu_processes;
  return `${backendLabel}: ${instance.name} (${machine}, ${others == null ? instance.status.toLowerCase() : otherGpuProcesses(others)})`;
}

function otherGpuProcesses(n: number): string {
  return count(n, "other GPU process", "other GPU processes");
}
