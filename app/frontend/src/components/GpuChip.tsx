import { Link } from "react-router";
import { useCompute } from "../backend/queries";
import { gpuSummary } from "../gpu";
import { Icon } from "./Icon";
import styles from "./GpuChip.module.css";

/** The GPU in one line, in the top bar of every page. Opens the GPU page. */
export function GpuChip() {
  const compute = useCompute();
  if (!compute.data) return null;
  const { tone, text } = gpuSummary(compute.data);
  return (
    <Link
      to="/gpu"
      className={`${styles.chip} ${styles[tone]}`}
      title={compute.data.session?.message ?? text}
      aria-label={`GPU: ${text}`}
    >
      <Icon name="chip" />
      <span className={styles.dot} aria-hidden="true" />
      <span className={styles.text}>{text}</span>
    </Link>
  );
}
