import { Link } from "react-router";
import { useCompute, useMeta } from "../backend/queries";
import { CAVEATS } from "../caveats";
import { duration } from "../format";
import { gpuSummary } from "../gpu";
import styles from "./StatusBar.module.css";

const TARGET_KIND = { mock: "mock target", brev: "Brev", gb10: "MSOE GB10" } as const;

/** The machine's state along the bottom of every page, like a terminal's status line: the GPU (opens the GPU page), how
 *  long it's been up, and which simulator answers. */
export function StatusBar() {
  const compute = useCompute();
  const meta = useMeta();
  const session = compute.data?.session;
  const gpu = compute.data && gpuSummary(compute.data);
  const upFor = session?.status === "ready" && session.ready_at ? Date.now() / 1000 - session.ready_at : null;
  const sim = meta.data?.sim;

  return (
    <footer className={styles.bar}>
      {gpu && (
        <Link to="/gpu" className={`${styles.item} ${styles.gpu} ${styles[gpu.tone]}`} title={session?.message ?? gpu.text}>
          <span className={styles.dot} aria-hidden="true" />
          {gpu.text}
        </Link>
      )}
      {session && <span className={styles.item}>{TARGET_KIND[session.backend]}</span>}
      {upFor !== null && <span className={styles.item}>up {duration(upFor)}</span>}
      {sim && (
        <span
          className={`${styles.item} ${styles.end} ${sim.badge === "mock" ? styles.warn : ""}`}
          title={sim.badge === "mock" ? CAVEATS.mock : (sim.url ?? undefined)}
        >
          {sim.badge === "mock" ? "mock sim" : "isaac sim"}
          {sim.url && <span className={styles.url}>{sim.url.replace(/^https?:\/\//, "")}</span>}
        </span>
      )}
    </footer>
  );
}
