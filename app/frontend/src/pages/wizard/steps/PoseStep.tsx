import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { api, unwrapAs, type Schemas } from "../../../backend/client";
import { meshUrl, usePart } from "../../../backend/queries";
import { Banner } from "../../../components/Banner";
import { PartViewer } from "../../../components/PartViewer";
import { ErrorState, Skeleton } from "../../../components/States";
import { dims, percent } from "../../../format";
import { useDraft, useStepGate, type DraftPose, type PoseChoice } from "../draft";
import { capitalise, choiceOf, findPose, sortByLikelihood, usePoses, weightOf, type Pose } from "../poses";
import styles from "../Wizard.module.css";

type Part = Schemas["PartResponse"];

/** Step 2: how the part comes to rest on the table. Every likely pose is ticked to start with; the job scores one finger
 *  in each ticked pose, weighted by how likely it is. "As in the CAD file" has no likelihood, so it stands alone. */
export function PoseStep() {
  const { draft, update } = useDraft();
  const part = usePart(draft.part_id);
  const id = draft.part_id;
  const queryClient = useQueryClient();
  const poses = usePoses(id);
  const ticked = draft.poses ?? [];

  // The part's own pose follows the primary: the library, the part page and the summary thumbnail show it.
  const setPartPose = useMutation({
    mutationFn: (pose: PoseChoice) =>
      unwrapAs<Part>(api.PATCH("/api/parts/{part_id}", { params: { path: { part_id: id! } }, body: { pose } })),
    onSuccess: (saved) => {
      queryClient.setQueryData(["parts", saved.id], saved);
      void queryClient.invalidateQueries({ queryKey: ["parts"] });
      // The chosen-pose mesh keeps its URL when the pose changes, so its cached copy (and thumbnail) would still show
      // the old pose
      void queryClient.resetQueries({ queryKey: ["mesh", meshUrl(saved.id)] });
    },
  });

  const choose = (next: DraftPose[], list: Pose[]) => {
    const sorted = sortByLikelihood(next, list);
    update({ poses: sorted });
    const primary = sorted[0] && findPose(list, sorted[0].pose);
    if (primary && !primary.chosen) setPartPose.mutate(sorted[0].pose);
  };

  // A new draft starts with every likely pose ticked (the likeliest if none is), once.
  const preselected = useRef(false);
  useEffect(() => {
    if (preselected.current || !poses.data || draft.poses) return;
    preselected.current = true;
    const likely = poses.data.filter((p) => p.likely);
    const start = likely.length > 0 ? likely : poses.data.slice(0, 1);
    choose(start.map((p) => ({ pose: choiceOf(p) })), poses.data);
  });

  useStepGate(
    2,
    !id ? { ok: false, reason: "Choose a part first" } : ticked.length > 0 ? { ok: true } : { ok: false, reason: "Tick at least one pose" },
  );

  if (!id) return <p className={styles.note}>Choose a part in step 1 first.</p>;
  if (poses.isPending) return <Skeleton height={220} />;
  if (poses.isError) return <ErrorState title="Couldn't work out the poses" message={poses.error.message} onRetry={() => poses.refetch()} />;

  const list = poses.data;
  const toggle = (pose: Pose) => {
    const choice = choiceOf(pose);
    const on = ticked.some((d) => d.pose === choice);
    if (on) return choose(ticked.filter((d) => d.pose !== choice), list);
    if (choice === "as_authored") return choose([{ pose: choice }], list);
    choose([...ticked.filter((d) => d.pose !== "as_authored"), { pose: choice }], list); // grasps of the others are kept
  };
  const coverage = ticked.reduce((sum, d) => sum + (findPose(list, d.pose)?.probability ?? 0), 0);

  return (
    <>
      <div className={styles.poseGrid} role="group" aria-label="Resting poses">
        {list.map((pose) => {
          const choice = choiceOf(pose);
          const on = ticked.some((d) => d.pose === choice);
          return (
            <button
              key={pose.index}
              type="button"
              role="checkbox"
              aria-checked={on}
              className={styles.choice}
              onClick={() => toggle(pose)}
            >
              <PartViewer url={meshUrl(id, choice)} label={`${part.data?.name ?? "The part"}, ${pose.label}`} mode="thumbnail" />
              <span className={styles.choiceLabel}>{capitalise(pose.label)}</span>
              <span className={styles.choiceNote}>
                {pose.probability != null && `${percent(pose.probability)} likely, `}
                {dims(pose.extent_mm)}
              </span>
              {on && ticked.length > 1 && <span className={styles.choiceNote}>{percent(weightOf(choice, ticked, list))} of the score</span>}
            </button>
          );
        })}
      </div>
      {setPartPose.error && <Banner tone="bad">{setPartPose.error.message}</Banner>}
      {coverage > 0 && (
        <p className={styles.note}>
          The ticked poses cover {percent(coverage)} of how the part comes to rest. One finger is scored in each, for its own
          grasp.
        </p>
      )}
    </>
  );
}
