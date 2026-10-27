import { useQuery } from "@tanstack/react-query";
import { api, unwrap, type Schemas } from "../../../backend/client";
import { useMeta } from "../../../backend/queries";
import { Notes } from "../../../components/Notes";
import { CAVEATS } from "../../../caveats";
import { isPlaceholderError, simPath } from "../describe";
import type { Results } from "../types";

type JobDetail = Schemas["JobDetailResponse"];

// The same thresholds as the part form's weak-grip warning (components/PartForm.tsx): heavier than about 100 g, or a
// static friction against the pad under 0.35.
const WEAK_GRIP_MASS_G = 100;
const WEAK_GRIP_FRICTION = 0.35;

/** The caveats above the fold (frontend-plan.md section 10), in one notice: the mock sim's "not a prediction", for Isaac
 *  results the known biases that apply to this run, the placeholders it ran with, and the run's own warnings, so nobody
 *  reads the numbers without them. */
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

  const notes = [
    ...(results.header.sim_backend === "mock" ? [`${CAVEATS.mock} No physics: these numbers show how the search works, not how the fingers will do.`] : []),
    ...(path?.exploratory ? [CAVEATS.gpuCopies] : []),
    ...isaac,
    ...(job.plan.poses.length > 1 ? [CAVEATS.poseRecognition] : []),
    ...(placeholderError ? [CAVEATS.placeholderError] : []),
    ...(mismatches.length > 0 ? [`${CAVEATS.twinMismatch} ${mismatches.join("; ")}.`] : []),
    ...results.run.warnings.map((w) => `From the run: ${w}.`),
  ];
  const serious = results.header.sim_backend === "mock" || Boolean(path?.exploratory);
  return <Notes title="What these numbers assume" tone={serious ? "warn" : "info"} notes={notes} />;
}
