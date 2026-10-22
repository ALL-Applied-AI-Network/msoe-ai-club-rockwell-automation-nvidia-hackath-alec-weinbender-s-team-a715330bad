import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { api, unwrapAs, type Schemas } from "../../../backend/client";
import { meshUrl, usePart } from "../../../backend/queries";
import { Banner } from "../../../components/Banner";
import { PartViewer } from "../../../components/PartViewer";
import { ErrorState, Skeleton } from "../../../components/States";
import { dims, percent } from "../../../format";
import { useDraft, useStepGate } from "../draft";
import styles from "../Wizard.module.css";

type Pose = Schemas["PoseResponse"];
type Part = Schemas["PartResponse"];

/** Step 2: how the part rests on the table. The likeliest stable poses as 3D thumbnails, plus "as in the CAD file";
 *  one click chooses. For a box or a cylinder the answer is obvious, so the likeliest is chosen already. */
export function PoseStep() {
  const { draft, update } = useDraft();
  const part = usePart(draft.part_id);
  const id = draft.part_id;
  const queryClient = useQueryClient();
  const poses = useQuery({
    queryKey: ["parts", id, "poses"],
    queryFn: () => unwrapAs<Pose[]>(api.GET("/api/parts/{part_id}/poses", { params: { path: { part_id: id! } } })),
    enabled: Boolean(id),
  });
  const choose = useMutation({
    mutationFn: (pose: number | "as_authored") =>
      unwrapAs<Part>(api.PATCH("/api/parts/{part_id}", { params: { path: { part_id: id! } }, body: { pose } })),
    onSuccess: (saved) => {
      queryClient.setQueryData(["parts", saved.id], saved);
      void queryClient.invalidateQueries({ queryKey: ["parts"] });
      update({ grasp: undefined }); // the grasp was found for the old pose
    },
  });

  const chosen = poses.data?.find((p) => p.chosen);
  useStepGate(
    2,
    !id ? { ok: false, reason: "Choose a part first" } : chosen && part.data?.pose ? { ok: true } : { ok: false, reason: "Choose how the part rests" },
  );

  // A box or a cylinder: preselect the likeliest pose, once, so Next accepts it.
  const preselected = useRef(false);
  const shape = part.data?.measured.suggested.shape;
  useEffect(() => {
    if (preselected.current || !poses.data || chosen || !shape || shape === "mesh") return;
    preselected.current = true;
    const likeliest = poses.data.find((p) => p.source === "stable");
    if (likeliest) choose.mutate(likeliest.index);
  }, [poses.data, chosen, shape, choose]);

  if (!id) return <p className={styles.note}>Choose a part in step 1 first.</p>;
  if (poses.isPending) return <Skeleton height={220} />;
  if (poses.isError) return <ErrorState title="Couldn't work out the poses" message={poses.error.message} onRetry={() => poses.refetch()} />;

  return (
    <>
      <div className={styles.poseGrid} role="radiogroup" aria-label="Resting pose">
        {poses.data.map((pose) => (
          <button
            key={pose.index}
            type="button"
            role="radio"
            aria-checked={pose.chosen}
            className={styles.choice}
            disabled={choose.isPending}
            onClick={() => !pose.chosen && choose.mutate(pose.source === "as_authored" ? "as_authored" : pose.index)}
          >
            <PartViewer
              url={meshUrl(id, pose.source === "as_authored" ? "as_authored" : pose.index)}
              label={`${part.data?.name ?? "The part"}, ${pose.label}`}
              mode="thumbnail"
            />
            <span className={styles.choiceLabel}>{capitalise(pose.label)}</span>
            <span className={styles.choiceNote}>
              {pose.probability != null ? `${percent(pose.probability)} likely` : "Exactly as the file has it"}, {dims(pose.extent_mm)}
            </span>
          </button>
        ))}
      </div>
      {choose.error && <Banner tone="bad">{choose.error.message}</Banner>}
      <p className={styles.note}>
        In a real cell, parts usually arrive in a tray or fixture, so you already know the pose. One pose per experiment:
        if parts arrive both ways, run two.
      </p>
    </>
  );
}

function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}
