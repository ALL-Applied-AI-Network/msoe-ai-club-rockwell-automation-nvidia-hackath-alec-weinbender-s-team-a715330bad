import type { Schemas } from "../../backend/client";
import { Banner } from "../../components/Banner";
import { LinkButton } from "../../components/Button";
import { of, percent } from "../../format";
import { wizardStep } from "../../labels";
import styles from "./JobPage.module.css";

type JobCard = Schemas["JobCard"];

/** A failed, cancelled or interrupted experiment (frontend-plan.md 6.3): why, what was kept, and how to carry on.
 *  Resume is in the header. */
export function Stopped({ card }: { card: JobCard }) {
  const step = wizardStep(card.failed_step);
  const kept =
    card.n_done > 0
      ? `Kept: round ${of(card.round, card.n_rounds)}, with ${of(card.n_done, card.n_total)} designs evaluated${
          card.best_value != null ? `, best ${percent(card.best_value)}` : ""
        }. Resume continues after the last finished round.`
      : "Nothing was evaluated yet. Resume starts it from the beginning.";

  if (card.status === "failed") {
    return (
      <Banner
        tone="bad"
        title="The experiment failed"
        action={
          step && (
            <LinkButton variant="primary" to={`/new/${step.slug}?from=${card.id}`}>
              Fix in step {card.failed_step}: {step.label}
            </LinkButton>
          )
        }
      >
        <span>
          {card.failure ?? "The job stopped with an error."} {step ? "The input in that step needs changing first." : kept}
        </span>
      </Banner>
    );
  }
  if (card.status === "interrupted") {
    return (
      <Banner tone="warn" title="Interrupted">
        <span>The computer running the app slept, shut down or restarted before the experiment finished. {kept}</span>
      </Banner>
    );
  }
  return (
    <Banner tone="info" title="Cancelled">
      <span className={styles.lead}>{kept}</span>
    </Banner>
  );
}
