import { useParams, useSearchParams } from "react-router";
import { LinkButton } from "../components/Button";
import { Page } from "../components/Page";
import { EmptyState } from "../components/States";
import { WIZARD_STEPS } from "../labels";

/** Stands in for a page that's planned but not built yet (docs/notes/frontend-plan.md), so every link already lands
 *  somewhere that says what will be there. */
export function NotBuiltPage({ title, plan }: { title: string; plan: string }) {
  return (
    <Page title={title}>
      <EmptyState
        title={plan}
        action={
          <LinkButton variant="secondary" to="/">
            Experiments
          </LinkButton>
        }
      />
    </Page>
  );
}

/** The wizard's routes, until it's built: names the step, and the experiment it would start from. */
export function WizardNotBuiltPage() {
  const { step } = useParams();
  const [params] = useSearchParams();
  const from = params.get("from");
  const index = WIZARD_STEPS.findIndex((s) => s.slug === step);
  const name = index >= 0 ? `step ${index + 1}, ${WIZARD_STEPS[index].label.toLowerCase()}` : "its first step";
  return (
    <NotBuiltPage
      title="New experiment"
      plan={`The new-experiment wizard will open here at ${name}${from ? `, filled in from experiment ${from}` : ""}.`}
    />
  );
}
