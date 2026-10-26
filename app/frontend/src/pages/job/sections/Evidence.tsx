import { useEffect, useState } from "react";
import { Segmented } from "../../../components/Segmented";
import { ClipsSection } from "../clips/ClipsSection";
import type { ClipPick, Results } from "../types";
import { Curves } from "./Curves";
import { Failures } from "./Failures";
import { HeldMaps } from "./HeldMaps";
import { InHand } from "./InHand";
import styles from "../JobPage.module.css";

type View = "curves" | "maps" | "failures" | "inhand" | "clips";

type EvidenceProps = {
  jobId: string;
  results: Results;
  picked: ClipPick | null; // a grasp picked on a held map, to film
  onPicked: (pick: ClipPick | null) => void;
};

/** The evidence behind the headline, one view at a time: success against camera error, the held maps, where the best
 *  design fails, the in-hand pose (place and insert), and the Isaac Sim clips. Picking a grasp on a held map opens the
 *  clips with it. */
export function Evidence({ jobId, results, picked, onPicked }: EvidenceProps) {
  const isaac = results.header.sim_backend === "isaac";
  const views: { value: View; label: string }[] = [
    ...(results.curves ? [{ value: "curves" as const, label: "Success against error" }] : []),
    ...(results.held_maps.length > 0 ? [{ value: "maps" as const, label: "Held maps" }] : []),
    ...(results.failures ? [{ value: "failures" as const, label: "Where it fails" }] : []),
    ...(results.in_hand && results.header.task.kind !== "drop" ? [{ value: "inhand" as const, label: "In the hand" }] : []),
    { value: "clips" as const, label: "Isaac Sim clips" },
  ];
  const [view, setView] = useState<View>(views[0].value);
  useEffect(() => {
    if (picked) setView("clips");
  }, [picked]);

  return (
    <section className={styles.evidence} aria-label="Evidence">
      <div className={styles.evidenceHead}>
        <h2 className={styles.evidenceTitle}>Evidence</h2>
        <Segmented label="Evidence" value={view} onChange={setView} options={views} />
      </div>
      {view === "curves" && <Curves results={results} />}
      {view === "maps" && <HeldMaps results={results} onPick={isaac ? onPicked : undefined} />}
      {view === "failures" && <Failures results={results} />}
      {view === "inhand" && <InHand results={results} />}
      {view === "clips" && <ClipsSection jobId={jobId} results={results} picked={picked} onPicked={onPicked} />}
    </section>
  );
}
