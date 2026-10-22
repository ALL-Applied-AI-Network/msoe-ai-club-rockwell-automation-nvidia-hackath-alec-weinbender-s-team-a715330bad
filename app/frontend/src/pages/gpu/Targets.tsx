import { useState } from "react";
import type { Schemas } from "../../backend/client";
import { Badge, type Tone } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Card } from "../../components/Card";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { HelpCard } from "../../components/HelpCard";
import { Icon } from "../../components/Icon";
import { KeyValues, type KeyValue } from "../../components/KeyValues";
import { Skeleton } from "../../components/States";
import { count } from "../../format";
import { gpuHelp } from "../../gpuHelp";
import { helpProps } from "./CurrentSession";
import { useComputeActions, useInstances } from "./queries";
import styles from "./GpuPage.module.css";

type Compute = Schemas["ComputeStatusResponse"];
type Instance = Schemas["ComputeInstance"];

const STATE: Record<Instance["state"], Tone> = {
  running: "ok",
  starting: "active",
  stopping: "warn",
  stopped: "neutral",
  other: "warn",
};

/** Every target the backend can use, one card each, with the button that starts or connects it. With a session active,
 *  the others offer to switch: stop or disconnect the current one, then start the chosen one. */
export function Targets({ compute }: { compute: Compute }) {
  const { session, backends } = compute;
  const connectedShared = session ? (backends.find((b) => b.name === session.backend)?.always_on ?? false) : false;
  const instances = useInstances(connectedShared);
  const { start, switchTo } = useComputeActions();
  const [failure, setFailure] = useState<{ target: Instance; message: string } | null>(null);
  const [switching, setSwitching] = useState<Instance | null>(null);
  const label = (name: Instance["backend"]) => backends.find((b) => b.name === name)?.label ?? name;
  const busy = start.isPending || switchTo.isPending;

  const go = (target: Instance) => {
    setFailure(null);
    start.mutate(target, { onError: (error) => setFailure({ target, message: error.message }) });
  };
  const doSwitch = (target: Instance) => {
    setFailure(null);
    switchTo.mutate(target, {
      onSuccess: () => setSwitching(null),
      onError: (error) => {
        setSwitching(null);
        setFailure({ target, message: error.message });
      },
    });
  };
  const inUse = (target: Instance) => session?.backend === target.backend && session.instance === target.name;

  return (
    <section className={styles.section} aria-labelledby="targets-title">
      <div className={styles.sectionHead}>
        <div>
          <h2 id="targets-title" className={styles.sectionTitle}>
            {session ? "Targets" : "Choose a target"}
          </h2>
          <p className={styles.note}>
            One target at a time. The list comes from COMPUTE_BACKENDS in the backend's .env; new Brev instances are
            made in the Brev console.
          </p>
        </div>
        <Button variant="secondary" size="sm" disabled={instances.isFetching} onClick={() => void instances.refetch()}>
          <Icon name="refresh" />
          {instances.isFetching ? "Asking the targets" : "Refresh the list"}
        </Button>
      </div>

      {failure && (
        <FailureHelp
          failure={failure}
          current={session?.instance}
          busy={busy}
          onRetry={() => go(failure.target)}
          onSwitch={() => doSwitch(failure.target)}
        />
      )}
      {switchTo.isPending && switching && (
        <p className={styles.note}>
          Stopping {session?.instance ?? "the current target"}, then starting {switching.name}.
        </p>
      )}

      {instances.isPending && (
        <div className={styles.targets}>
          {[0, 1].map((i) => (
            <Skeleton key={i} height={170} />
          ))}
        </div>
      )}
      {instances.isError && (
        <HelpCard message={instances.error.message} {...helpProps(instances.error.message)} action={<RetryButton onClick={() => void instances.refetch()} />} />
      )}
      {instances.data && (
        <>
          {instances.data.errors.map((error) => (
            <HelpCard
              key={error.backend}
              message={`${label(error.backend)}: ${error.message}`}
              {...helpProps(error.message)}
              action={<RetryButton onClick={() => void instances.refetch()} />}
            />
          ))}
          {instances.data.instances.length === 0 && instances.data.errors.length === 0 && (
            <p className={styles.note}>No targets: enable brev or gb10 in COMPUTE_BACKENDS, or create a Brev instance.</p>
          )}
          <div className={styles.targets}>
            {instances.data.instances.map((target) => (
              <TargetCard
                key={`${target.backend}/${target.name}`}
                target={target}
                backendLabel={label(target.backend)}
                inUse={inUse(target)}
                otherActive={Boolean(session) && !inUse(target)}
                busy={busy}
                onStart={() => go(target)}
                onSwitch={() => setSwitching(target)}
              />
            ))}
          </div>
        </>
      )}

      <ConfirmDialog
        open={switching !== null && !switchTo.isPending}
        title={switching ? `Switch to ${switching.name}?` : ""}
        confirmLabel={session && !connectedShared ? `Stop ${session.instance} and switch` : "Disconnect and switch"}
        cancelLabel="Stay on this one"
        onConfirm={() => switching && doSwitch(switching)}
        onClose={() => setSwitching(null)}
      >
        {connectedShared
          ? `The app disconnects from ${session?.instance} (its sim server keeps running for teammates), then starts ${switching?.name}.`
          : `The app stops ${session?.instance}, waits until it has stopped, then starts ${switching?.name}.`}{" "}
        Running jobs wait for the new target.
      </ConfirmDialog>
    </section>
  );
}

function TargetCard({
  target,
  backendLabel,
  inUse,
  otherActive,
  busy,
  onStart,
  onSwitch,
}: {
  target: Instance;
  backendLabel: string;
  inUse: boolean;
  otherActive: boolean;
  busy: boolean;
  onStart: () => void;
  onSwitch: () => void;
}) {
  const facts: KeyValue[] = [
    { label: "GPU", value: target.gpu ?? "Not reported" },
    { label: "Machine", value: target.instance_type ?? "Not reported" },
  ];
  if (target.other_gpu_processes != null) {
    facts.push({ label: "On it right now", value: count(target.other_gpu_processes, "other GPU process", "other GPU processes") });
  }
  facts.push({ label: "Role", value: target.always_on ? "Always on, shared with other teams, free" : "Started when needed, uses credits" });

  return (
    <Card
      title={target.name}
      subtitle={backendLabel}
      aside={<Badge tone={STATE[target.state]} label={sentence(target.status)} title="What the provider reports" />}
      footer={
        <div className={styles.actions}>
          {inUse ? (
            <Badge tone="ok" label="In use" dot />
          ) : otherActive ? (
            <Button variant="secondary" disabled={busy} onClick={onSwitch}>
              Switch to this target
            </Button>
          ) : (
            <Button disabled={busy} onClick={onStart}>
              {target.always_on ? "Connect" : "Start the GPU"}
            </Button>
          )}
        </div>
      }
    >
      <KeyValues items={facts} />
    </Card>
  );
}

/** Help for a start that failed: the switch button for "stop it before starting another target", else Try again. */
function FailureHelp({
  failure,
  current,
  busy,
  onRetry,
  onSwitch,
}: {
  failure: { target: Instance; message: string };
  current: string | undefined;
  busy: boolean;
  onRetry: () => void;
  onSwitch: () => void;
}) {
  const help = gpuHelp(failure.message);
  const action =
    help.action === "switch" ? (
      <Button disabled={busy} onClick={onSwitch}>
        {current ? `Stop ${current} and start ${failure.target.name}` : `Start ${failure.target.name}`}
      </Button>
    ) : help.action === "retry" ? (
      <RetryButton disabled={busy} onClick={onRetry} />
    ) : undefined;
  return <HelpCard message={failure.message} {...helpProps(failure.message)} action={action} />;
}

function RetryButton({ onClick, disabled }: { onClick: () => void; disabled?: boolean }) {
  return (
    <Button variant="secondary" size="sm" disabled={disabled} onClick={onClick}>
      Try again
    </Button>
  );
}

/** "STOPPED" or "AVAILABLE", as a provider reports it, in sentence case. */
function sentence(status: string): string {
  return status.charAt(0).toUpperCase() + status.slice(1).toLowerCase();
}
