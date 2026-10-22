import { useMeta } from "../../backend/queries";
import { SimBadge } from "../../components/Badges";
import { Card } from "../../components/Card";
import { KeyValues } from "../../components/KeyValues";
import { ErrorState, Skeleton } from "../../components/States";
import { CAVEATS } from "../../caveats";
import { count } from "../../format";
import styles from "./Settings.module.css";

/** #/settings/about: what this app is running on, from /api/meta (docs/notes/frontend-plan.md, 9.3). */
export function AboutSection() {
  const meta = useMeta();
  if (meta.isPending) return <Skeleton height={200} />;
  if (meta.isError) return <ErrorState title="Couldn't load the app's settings" message={meta.error.message} onRetry={() => meta.refetch()} />;
  const { sim, llm, demo_data, cpus } = meta.data;

  return (
    <Card title="About Auto-Grasp">
      <KeyValues
        items={[
          { label: "Simulator", value: <SimBadge backend={sim.badge} /> },
          { label: "Sim backend", value: sim.backend === "mock" ? "Mock, inside the API" : "HTTP, the sim server next to Isaac Sim", mono: false },
          { label: "Sim server address", value: sim.url ?? "None: the mock runs inside the API", mono: Boolean(sim.url) },
          { label: "LLM step", value: llm, mono: true },
          { label: "Demo data", value: demo_data ? "On" : "Off" },
          { label: "CPUs", value: cpus == null ? "Unknown" : count(cpus, "CPU", "CPUs") },
          { label: "App version", value: "Not numbered yet" },
        ]}
      />
      {sim.badge === "mock" && <p className={styles.note}>{CAVEATS.mock}</p>}
      {demo_data && <p className={styles.note}>{CAVEATS.demoData}</p>}
    </Card>
  );
}
