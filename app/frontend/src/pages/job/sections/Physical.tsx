import type { Schemas } from "../../../backend/client";
import { PhysicalBadge } from "../../../components/Badges";
import { LinkButton } from "../../../components/Button";
import { Card } from "../../../components/Card";
import { EmptyState } from "../../../components/States";
import { Table, type Column } from "../../../components/Table";
import { percent } from "../../../format";
import { designLabel } from "../../../labels";
import type { Results } from "../types";
import styles from "../JobPage.module.css";

type DesignValidation = Schemas["DesignValidation"];

const COLUMNS: Column<DesignValidation>[] = [
  { key: "design", header: "Design", render: (d) => <strong className={styles.design}>{designLabel(d.design_label)}</strong> },
  {
    key: "predicted",
    header: "Predicted",
    align: "right",
    render: (d) => (d.predicted_success == null ? "none" : percent(d.predicted_success)),
  },
  {
    key: "measured",
    header: "Measured",
    align: "right",
    render: (d) => (d.measured_success == null ? "none yet" : percent(d.measured_success)),
  },
  { key: "summary", header: "Agreement", render: (d) => d.summary },
];

/** The robot's side of the story (frontend-plan.md 7.1): what's been measured so far, and the way into the validation
 *  flow. */
export function Physical({ jobId, results }: { jobId: string; results: Results }) {
  const physical = results.physical;
  const link = (
    <LinkButton variant="secondary" size="sm" to={`/jobs/${jobId}/validation`}>
      Open the validation
    </LinkButton>
  );
  return (
    <Card title="Physical validation" aside={<PhysicalBadge status={physical.badge} />}>
      {physical.designs.length === 0 ? (
        <EmptyState title="No physical trials yet" action={link}>
          Measured success shows here beside the prediction.
        </EmptyState>
      ) : (
        <>
          <Table label="Predicted against measured" columns={COLUMNS} rows={physical.designs} rowKey={(d) => d.design_label} />
          <div>{link}</div>
        </>
      )}
    </Card>
  );
}
