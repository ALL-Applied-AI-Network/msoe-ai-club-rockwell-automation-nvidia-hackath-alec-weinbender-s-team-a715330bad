import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { CAVEATS } from "../../caveats";
import styles from "./Cells.module.css";

/** Beside a field that's still a placeholder (in the profile's `to_confirm`): the mark, and a button to clear it once
 *  the value has been measured at the cell. Clearing takes effect when the profile is saved. */
export function PlaceholderMark({ onMeasured }: { onMeasured: () => void }) {
  return (
    <span className={styles.mark}>
      <Badge tone="warn" label="Placeholder" title={CAVEATS.placeholderCell} />
      <Button variant="ghost" size="sm" onClick={onMeasured} title="Clear the mark: this value is measured">
        Mark as measured
      </Button>
    </span>
  );
}
