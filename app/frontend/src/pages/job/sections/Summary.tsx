import { Card } from "../../../components/Card";
import { Stat } from "../../../components/Stat";
import type { Schemas } from "../../../backend/client";
import { mm, percent, points } from "../../../format";
import { designLabel } from "../../../labels";
import type { Results } from "../types";
import styles from "../JobPage.module.css";

type Score = Schemas["DesignScore"];

/** The one-glance answer: the best design against the stock fingers and the imprint, at the target camera error. */
export function Summary({ results }: { results: Results }) {
  const summary = results.summary!;
  const { best, stock, imprint, task_metric_label: metricLabel } = summary;
  const sigma = results.header.error.sigma_mm;
  const detail = (score: Score) => (
    <>
      {score.capture_radius_mm == null ? "no capture radius" : `capture radius ${mm(score.capture_radius_mm)}`}
      {metricLabel && score.task_metric != null && (
        <>
          <br />
          {percent(score.task_metric)} {metricLabel}
        </>
      )}
    </>
  );

  return (
    <Card
      title="Summary"
      subtitle={`At the target camera error, σ ${mm(sigma)}: the share of grasps each finger holds, and how far off centre it still catches the part.`}
    >
      <p className={styles.lead}>
        {designLabel(best.label)} holds {percent(best.success)} of grasps
        {stock ? `, against ${percent(stock.success)} for the stock fingers` : ""}
        {imprint ? ` and ${percent(imprint.success)} for the imprint` : ""}.
      </p>
      <div className={styles.summary}>
        <Stat size="lg" tone="acc" label={`Best design, ${designLabel(best.label)}`} value={percent(best.success)} detail={detail(best)} />
        {stock && (
          <Stat
            size="lg"
            label="Stock fingers"
            value={percent(stock.success)}
            detail={
              <>
                {detail(stock)}
                {summary.gain_vs_stock != null && (
                  <>
                    <br />
                    {designLabel(best.label)}: {points(summary.gain_vs_stock)}
                  </>
                )}
              </>
            }
          />
        )}
        {imprint && (
          <Stat
            size="lg"
            label="Imprint"
            value={percent(imprint.success)}
            detail={
              <>
                {detail(imprint)}
                {summary.gain_vs_imprint != null && (
                  <>
                    <br />
                    {designLabel(best.label)}: {points(summary.gain_vs_imprint)}
                  </>
                )}
              </>
            }
          />
        )}
        <Stat size="lg" label="Designs evaluated" value={String(summary.designs_evaluated)} detail="across every search" />
      </div>
    </Card>
  );
}
