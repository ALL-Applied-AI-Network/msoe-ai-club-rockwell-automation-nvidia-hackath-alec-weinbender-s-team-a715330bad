import { useQuery } from "@tanstack/react-query";
import { api, unwrap, type Schemas } from "../../../backend/client";
import { useMeta } from "../../../backend/queries";
import { Banner } from "../../../components/Banner";
import { CAVEATS } from "../../../caveats";
import { isPlaceholderError, simPath } from "../describe";
import type { Results } from "../types";
import styles from "../JobPage.module.css";

type JobDetail = Schemas["JobDetailResponse"];

// The same thresholds as the part form's weak-grip warning (components/PartForm.tsx): heavier than about 100 g, or a
// static friction against the pad under 0.35.
const WEAK_GRIP_MASS_G = 100;
const WEAK_GRIP_FRICTION = 0.35;

/** The caveats above the fold (frontend-plan.md section 10): the mock sim's "not a prediction", and for Isaac results the
 *  known biases that apply to this run, so nobody reads the numbers without them. */
export function ResultBanners({ job, results }: { job: JobDetail; results: Results }) {
  const meta = useMeta();
  const profile = useQuery({
    queryKey: ["cell-profiles", job.cell_profile_id],
    queryFn: () =>
      unwrap(api.GET("/api/cell-profiles/{profile_id}", { params: { path: { profile_id: job.cell_profile_id } } })),
  });
  const mismatches = profile.data?.twin_mismatches ?? [];
  const path = simPath(results.run.sim);
  const weak = job.part.mass_g > WEAK_GRIP_MASS_G || job.part.friction[0] < WEAK_GRIP_FRICTION;
  const placeholderError = isPlaceholderError(results.header.error, meta.data);

  const isaac: string[] = [];
  if (results.header.sim_backend === "isaac") {
    isaac.push(CAVEATS.landingCapture);
    if (weak) isaac.push(CAVEATS.weakGrip);
  }

  return (
    <>
      {results.header.sim_backend === "mock" && (
        <Banner tone="warn" title="Mock sim">
          {CAVEATS.mock} It checks capture geometry only, with no physics, so these numbers show how the search works,
          not how the fingers will do.
        </Banner>
      )}
      {path?.exploratory && (
        <Banner tone="warn" title="Exploratory sim path">
          {CAVEATS.gpuCopies}
        </Banner>
      )}
      {isaac.length > 0 && (
        <Banner tone="info" title="Read these numbers with the twin's known biases">
          <ul className={styles.list}>
            {isaac.map((text) => (
              <li key={text}>{text}</li>
            ))}
          </ul>
        </Banner>
      )}
      {(placeholderError || mismatches.length > 0) && (
        <Banner tone="info" title="Placeholders in this run">
          <ul className={styles.list}>
            {placeholderError && <li>{CAVEATS.placeholderError}</li>}
            {mismatches.length > 0 && (
              <li>
                {CAVEATS.twinMismatch} {mismatches.join("; ")}.
              </li>
            )}
          </ul>
        </Banner>
      )}
    </>
  );
}
