import type { Schemas } from "../../backend/client";
import { Badge } from "../../components/Badge";
import { Table } from "../../components/Table";
import { ErrorState, Skeleton } from "../../components/States";
import { dateTime, duration } from "../../format";
import { useNow, useSessions } from "./queries";
import styles from "./GpuPage.module.css";

type Session = Schemas["ComputeSession"];
type Backend = Schemas["BackendInfo"];

const ENDED: Record<NonNullable<Session["stop_reason"]>, string> = {
  user: "Ended from the app",
  idle: "Stopped after the idle time",
  external: "Stopped outside the app",
  failed: "Failed",
};

/** The record of GPU time: which target was connected when, for how long, and why it ended (plan 4.3). */
export function SessionLog({ backends }: { backends: Backend[] }) {
  const sessions = useSessions();
  const now = useNow(sessions.data?.some((s) => !s.stopped_at) ?? false);
  const label = (name: Session["backend"]) => backends.find((b) => b.name === name)?.label ?? name;

  return (
    <section className={styles.section} aria-labelledby="log-title">
      <div>
        <h2 id="log-title" className={styles.sectionTitle}>
          Session log
        </h2>
        <p className={styles.note}>Every GPU session from this app, latest first: the record of GPU time and credits.</p>
      </div>
      {sessions.isPending && <Skeleton height={120} />}
      {sessions.isError && (
        <ErrorState title="Couldn't load the session log" message={sessions.error.message} onRetry={() => void sessions.refetch()} />
      )}
      {sessions.data && (
        <Table
          label="GPU sessions"
          rows={sessions.data}
          rowKey={(s) => String(s.id)}
          rowTone={(s) => (s.status === "failed" ? "bad" : undefined)}
          empty="No sessions yet: connect a target above."
          columns={[
            {
              key: "target",
              header: "Target",
              render: (s) => (
                <>
                  <div className={styles.cellStrong}>{s.instance}</div>
                  <div className={styles.cellSub}>{label(s.backend)}</div>
                </>
              ),
              sortValue: (s) => s.instance,
            },
            { key: "started", header: "Asked for", render: (s) => dateTime(s.requested), sortValue: (s) => s.requested },
            {
              key: "up",
              header: "Up for",
              align: "right",
              render: (s) => (s.ready_at ? duration((s.stopped_at ?? now) - s.ready_at) : "Never ready"),
              sortValue: (s) => (s.ready_at ? (s.stopped_at ?? now) - s.ready_at : null),
            },
            {
              key: "ended",
              header: "How it ended",
              render: (s) =>
                s.stopped_at ? (
                  <span title={s.message ?? undefined}>{s.stop_reason ? ENDED[s.stop_reason] : "Stopped"}</span>
                ) : (
                  <Badge tone={s.status === "ready" ? "ok" : "active"} label="In use" />
                ),
            },
          ]}
        />
      )}
    </section>
  );
}
