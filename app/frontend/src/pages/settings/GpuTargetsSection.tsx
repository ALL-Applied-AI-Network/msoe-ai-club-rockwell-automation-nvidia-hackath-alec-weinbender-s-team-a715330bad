import type { Schemas } from "../../backend/client";
import { useCompute } from "../../backend/queries";
import { Badge } from "../../components/Badge";
import { Banner } from "../../components/Banner";
import { LinkButton } from "../../components/Button";
import { Card } from "../../components/Card";
import { KeyValues } from "../../components/KeyValues";
import { ErrorState, Skeleton } from "../../components/States";
import { Table } from "../../components/Table";
import { minutes } from "../../format";
import styles from "./Settings.module.css";

type Backend = Schemas["BackendInfo"];

const ROLE: Record<Backend["name"], string> = {
  gb10: "The MSOE GB10: free, shared with other teams. Connected and disconnected, never stopped.",
  brev: "The team's Brev instances: paid. Started and stopped from the app, and stopped by themselves when idle.",
  mock: "Made-up targets, for working on the app offline. Results from the mock sim are never predictions.",
};

/** #/settings/gpu: which GPU targets the backend has enabled. Read-only: they're set in the backend's .env, since they
 *  hold machine paths that must match each user's own setup (docs/notes/frontend-plan.md, 9.2). */
export function GpuTargetsSection() {
  const compute = useCompute();
  if (compute.isPending) return <Skeleton height={240} />;
  if (compute.isError) {
    return <ErrorState title="Couldn't load the GPU settings" message={compute.error.message} onRetry={() => compute.refetch()} />;
  }
  const { backends, managed, auto_stop_minutes } = compute.data;
  const brev = backends.some((b) => b.name === "brev");

  return (
    <div className={styles.section}>
      <Card
        title="Enabled GPU targets"
        aside={
          <LinkButton variant="secondary" size="sm" to="/gpu">
            Open the GPU page
          </LinkButton>
        }
      >
        <Table
          label="Enabled GPU targets"
          rows={backends}
          rowKey={(b) => b.name}
          columns={[
            { key: "label", header: "Target", render: (b) => b.label },
            { key: "name", header: "Setting", render: (b) => <code>{b.name}</code> },
            {
              key: "always_on",
              header: "Runs",
              render: (b) => (b.always_on ? <Badge tone="neutral" label="Always on, shared" /> : <Badge tone="neutral" label="Started from the app" />),
            },
            { key: "role", header: "What it is", render: (b) => ROLE[b.name] },
          ]}
        />
        <KeyValues
          items={[
            {
              label: "Jobs wait for a GPU",
              value: managed ? "Yes: new jobs and resumes need a ready GPU" : "No: only the mock targets are enabled",
            },
            ...(brev ? [{ label: "Brev stops by itself after", value: auto_stop_minutes > 0 ? `${minutes(auto_stop_minutes)} idle` : "Never: auto-stop is off" }] : []),
          ]}
        />
      </Card>
      <Banner tone="info" title="Changing them">
        Targets are set in the backend's .env file, with COMPUTE_BACKENDS and the COMPUTE_ settings, and take effect when the
        API restarts. SETUP.md, "GPU from the web app", has what each person sets up for Brev and the GB10.
      </Banner>
    </div>
  );
}
