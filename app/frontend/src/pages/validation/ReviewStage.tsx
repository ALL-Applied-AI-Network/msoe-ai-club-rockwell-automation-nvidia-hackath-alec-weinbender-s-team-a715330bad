import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { api, unwrap, type Schemas } from "../../backend/client";
import type { Tone } from "../../components/Badge";
import { Button } from "../../components/Button";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Field, fieldStyles, TextInput } from "../../components/Field";
import { KeyValues } from "../../components/KeyValues";
import { dateTime } from "../../format";
import { useRefreshJob } from "./queries";
import { Stage } from "./Stage";
import styles from "./JobValidationPage.module.css";

type Review = Schemas["Review"];
type Decision = "approved" | "rejected" | "pending";

const STATUS: Record<Review["status"], { tone: Tone; label: string }> = {
  approved: { tone: "ok", label: "Approved for the robot" },
  rejected: { tone: "bad", label: "Rejected" },
  pending: { tone: "warn", label: "Not approved yet" },
};

/** Stage 3, the plant's safety gate (frontend-plan.md 7.4): no printed finger goes on the real arm until a named
 *  reviewer approves it. Approving asks first, naming who approves what. */
export function ReviewStage({ jobId, experimentId, review }: { jobId: string; experimentId: string; review: Review | null | undefined }) {
  const refresh = useRefreshJob(jobId);
  const [reviewer, setReviewer] = useState("");
  const [notes, setNotes] = useState("");
  const [confirming, setConfirming] = useState(false);
  const submit = useMutation({
    mutationFn: (status: Decision) =>
      unwrap(
        api.POST("/api/jobs/{job_id}/review", {
          params: { path: { job_id: jobId } },
          body: { status, reviewer: reviewer.trim(), notes: notes.trim() },
          bodySerializer: (body) => new URLSearchParams(body as Record<string, string>),
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
        }),
      ),
    onSuccess: () => {
      setConfirming(false);
      setNotes("");
    },
    onSettled: refresh,
  });
  const decided = review && review.status !== "pending";
  const approved = review?.status === "approved";

  return (
    <Stage
      step={3}
      title="Approve for the robot"
      status={STATUS[review?.status ?? "pending"]}
      description="Printed fingers go on the real arm only after a named reviewer checks them for clearance and safe operation."
    >
      {decided && (
        <KeyValues
          inline
          items={[
            { label: "Reviewer", value: review.reviewer || "Not named" },
            { label: "When", value: dateTime(review.created) },
            ...(review.notes ? [{ label: "Notes", value: review.notes }] : []),
          ]}
        />
      )}
      {!approved && (
        <div className={styles.formRow}>
          <TextInput label="Reviewer" value={reviewer} onChange={setReviewer} placeholder="Your name" hint="Required to approve." autoComplete="name" />
          <Field label="Notes" hint="Optional">
            {(id) => <input id={id} className={fieldStyles.control} value={notes} onChange={(event) => setNotes(event.target.value)} />}
          </Field>
        </div>
      )}
      <div className={styles.actions}>
        {!approved && (
          <>
            <Button disabled={!reviewer.trim() || submit.isPending} onClick={() => setConfirming(true)}>
              Approve for the robot
            </Button>
            <Button variant="danger" disabled={submit.isPending} onClick={() => submit.mutate("rejected")}>
              Reject
            </Button>
          </>
        )}
        {decided && (
          <Button variant="ghost" disabled={submit.isPending} onClick={() => submit.mutate("pending")}>
            Mark as not reviewed
          </Button>
        )}
      </div>
      {submit.error && !confirming && <p className={styles.error}>{submit.error.message}</p>}
      <ConfirmDialog
        open={confirming}
        title={`Approve ${experimentId} for the robot?`}
        confirmLabel="Approve under my name"
        cancelLabel="Go back"
        pending={submit.isPending}
        error={submit.error?.message}
        onConfirm={() => submit.mutate("approved")}
        onClose={() => setConfirming(false)}
      >
        {reviewer.trim()} approves this experiment's printed fingers to go on the real arm, for supervised tests at the
        cell. The approval is recorded with the name and the time.
      </ConfirmDialog>
    </Stage>
  );
}
