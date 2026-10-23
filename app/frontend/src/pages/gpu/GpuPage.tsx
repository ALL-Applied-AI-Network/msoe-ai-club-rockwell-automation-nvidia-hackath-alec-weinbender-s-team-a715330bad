import { useCompute } from "../../backend/queries";
import { Banner } from "../../components/Banner";
import { Button } from "../../components/Button";
import { HelpCard } from "../../components/HelpCard";
import { Page } from "../../components/Page";
import { ErrorState, Skeleton } from "../../components/States";
import { clockTime } from "../../format";
import { CurrentSession, helpProps } from "./CurrentSession";
import { useComputeActions, useInstances, useSessions } from "./queries";
import { SessionLog } from "./SessionLog";
import { SetupHelp } from "./SetupHelp";
import { Targets } from "./Targets";
import styles from "./GpuPage.module.css";

/** #/gpu: the GPU the Isaac sim runs on (docs/notes/frontend-plan.md, section 4). The current session, the targets to
 *  choose from, the session log, and how to set each target up. Every error comes with a help card. */
export function GpuPage() {
  const compute = useCompute();
  const sessions = useSessions();
  const data = compute.data;
  const connectedShared = data?.session ? (data.backends.find((b) => b.name === data.session!.backend)?.always_on ?? false) : false;
  const instances = useInstances(connectedShared);
  const { start } = useComputeActions();
  const onlyMock = data ? data.backends.every((b) => b.name === "mock") : false;
  const neverConnected = sessions.data !== undefined && !sessions.data.some((s) => s.ready_at);
  const lastFailed = data && !data.session && data.last?.status === "failed" ? data.last : null;
  const retryTarget = lastFailed
    ? instances.data?.instances.find((i) => i.backend === lastFailed.backend && i.name === lastFailed.instance)
    : undefined;

  return (
    <Page title="GPU">
      {compute.isPending && <Skeleton height={160} />}
      {compute.isError && (
        <ErrorState title="Couldn't load the GPU status" message={compute.error.message} onRetry={() => void compute.refetch()} />
      )}
      {data && (
        <>
          {onlyMock && (
            <Banner tone="info" title="Mock targets only.">
              Add brev or gb10 to COMPUTE_BACKENDS in the backend's .env for real ones.
            </Banner>
          )}
          {data.session ? (
            <CurrentSession
              compute={data}
              session={data.session}
              target={instances.data?.instances.find(
                (i) => i.backend === data.session!.backend && i.name === data.session!.instance,
              )}
            />
          ) : (
            <>
              {data.not_ready_reason && <Banner tone="warn">{data.not_ready_reason}</Banner>}
              {lastFailed?.message && (
                <div className={styles.section}>
                  <p className={styles.note}>
                    The last session, {lastFailed.instance}, failed
                    {lastFailed.stopped_at ? ` at ${clockTime(lastFailed.stopped_at)}` : ""}.
                  </p>
                  <HelpCard
                    message={lastFailed.message}
                    {...helpProps(lastFailed.message)}
                    action={
                      retryTarget && (
                        <Button variant="secondary" size="sm" disabled={start.isPending} onClick={() => start.mutate(retryTarget)}>
                          Try again
                        </Button>
                      )
                    }
                  />
                </div>
              )}
            </>
          )}
          <Targets compute={data} />
          <SessionLog backends={data.backends} />
          <SetupHelp backends={data.backends} open={neverConnected && !data.session} />
        </>
      )}
    </Page>
  );
}
