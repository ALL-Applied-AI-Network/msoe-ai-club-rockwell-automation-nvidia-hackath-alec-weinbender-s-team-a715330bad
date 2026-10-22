import type { Schemas } from "../../../backend/client";
import { Banner } from "../../../components/Banner";
import { Card } from "../../../components/Card";
import { BinChart } from "../../../components/charts/BinChart";
import { Table, type Column } from "../../../components/Table";
import { CAVEATS } from "../../../caveats";
import { degrees, mm, of, percent } from "../../../format";
import { designLabel } from "../../../labels";
import type { Results } from "../types";
import styles from "../JobPage.module.css";

type MissGroup = Schemas["MissGroup"];

const COLUMNS: Column<MissGroup>[] = [
  { key: "direction", header: "Direction", render: (g) => `${g.direction} (${degrees(g.angle_deg)})` },
  { key: "missed", header: "Missed", align: "right", sortValue: (g) => g.missed / (g.points || 1), render: (g) => of(g.missed, g.points) },
  {
    key: "nearest",
    header: "Nearest miss",
    align: "right",
    sortValue: (g) => g.nearest_miss_mm,
    render: (g) => (g.nearest_miss_mm == null ? "none" : mm(g.nearest_miss_mm)),
  },
  { key: "lost", header: "Success lost", align: "right", sortValue: (g) => g.lost, render: (g) => percent(g.lost) },
];

/** Where the best design fails (frontend-plan.md 7.1): misses by direction and by distance, and the standing caveats.
 *  The judges asked for failure cases, so they're shown as plainly as the successes. */
export function Failures({ results }: { results: Results }) {
  const view = results.failures!;
  const caveats = view.caveats.some((c) => c.toLowerCase().includes("friction"))
    ? view.caveats
    : [...view.caveats, CAVEATS.estimatedFriction];
  return (
    <Card
      title="Where it fails"
      subtitle={`${designLabel(view.label)}'s misses on the final grid. x is the jaws' closing direction.`}
    >
      {view.centre_missed ? (
        <Banner tone="bad" title="It misses even at the centre">
          A grasp with no camera error at all fails, so the design or the grasp needs another look.
        </Banner>
      ) : (
        <p className={styles.lead}>
          {view.first_miss_mm == null
            ? "No misses anywhere on the grid."
            : `It holds every grasp up to ${mm(view.first_miss_mm)} off centre; the first miss is there.`}
        </p>
      )}
      <div className={styles.pair}>
        <Table label="Misses by direction" columns={COLUMNS} rows={view.by_direction} rowKey={(g) => g.direction} />
        <BinChart
          bins={view.by_distance.map((d) => ({
            key: String(d.radius_mm),
            x: d.radius_mm,
            value: d.points ? d.missed / d.points : 0,
            details: [{ label: "missed", value: of(d.missed, d.points) }],
          }))}
          color="bad"
          xLabel="Distance from the centre (mm)"
          yLabel="Share missed"
          formatX={(x) => `${mm(x)} off centre`}
          summary={`Share of grasps missed at each distance from the centre; the first miss is at ${
            view.first_miss_mm == null ? "no distance" : mm(view.first_miss_mm)
          }.`}
        />
      </div>
      <ul className={styles.list}>
        {caveats.map((c) => (
          <li key={c}>{sentence(c)}</li>
        ))}
      </ul>
    </Card>
  );
}

/** The backend writes its caveats in lower case without a full stop. */
function sentence(text: string): string {
  const trimmed = text.trim();
  return trimmed.charAt(0).toUpperCase() + trimmed.slice(1) + (/[.!?]$/.test(trimmed) ? "" : ".");
}
