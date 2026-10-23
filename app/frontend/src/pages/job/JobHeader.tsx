import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { api, unwrap, type Schemas } from "../../backend/client";
import { useCompute, useMeta } from "../../backend/queries";
import { Badge } from "../../components/Badge";
import { canResume, isActive, JobStatusBadge, PhysicalBadge, SimBadge } from "../../components/Badges";
import { Button, LinkButton } from "../../components/Button";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { TextInput } from "../../components/Field";
import { KeyValues } from "../../components/KeyValues";
import { Tabs } from "../../components/Tabs";
import { CAVEATS } from "../../caveats";
import { dateTime } from "../../format";
import { errorText, posesText, simPath, taskText } from "./describe";
import { useRefresh } from "./queries";
import type { Results } from "./types";
import styles from "./JobPage.module.css";

type JobDetail = Schemas["JobDetailResponse"];

/** The experiment's name and ID (renamable in place), its badges and settings, and what can be done with it. */
export function JobHeader({ job, results }: { job: JobDetail; results: Results | undefined }) {
  const meta = useMeta();
  const compute = useCompute();
  const refresh = useRefresh(job.id);
  const card = job.card;
  const path = simPath(results?.run.sim);
  const notReady = compute.data?.not_ready_reason;

  const [renaming, setRenaming] = useState<string | null>(null);
  const rename = useMutation({
    mutationFn: (name: string) =>
      unwrap(api.PATCH("/api/jobs/{job_id}", { params: { path: { job_id: job.id } }, body: { name } })),
    onSuccess: () => setRenaming(null),
    onSettled: refresh,
  });
  const [confirming, setConfirming] = useState(false);
  const cancel = useMutation({
    mutationFn: () => unwrap(api.POST("/api/jobs/{job_id}/cancel", { params: { path: { job_id: job.id } } })),
    onSuccess: () => setConfirming(false),
    onSettled: refresh,
  });
  const resume = useMutation({
    mutationFn: () => unwrap(api.POST("/api/jobs/{job_id}/resume", { params: { path: { job_id: job.id } } })),
    onSettled: refresh,
  });
  const active = isActive(card.status);
  const header = results?.header;

  return (
    <header className={styles.header}>
      <div className={styles.titleRow}>
        {renaming === null ? (
          <h1 className={styles.title}>
            {card.name}
            <code className={styles.id}>{card.experiment_id}</code>
            <Button variant="ghost" size="sm" onClick={() => setRenaming(card.name)}>
              Rename
            </Button>
          </h1>
        ) : (
          <form
            className={styles.rename}
            onSubmit={(event) => {
              event.preventDefault();
              if (renaming.trim()) rename.mutate(renaming.trim());
            }}
          >
            <div className={styles.grow}>
              <TextInput
                label={`Name of ${card.experiment_id}`}
                value={renaming}
                onChange={setRenaming}
                autoFocus
                error={rename.error?.message}
              />
            </div>
            <Button type="submit" disabled={!renaming.trim() || rename.isPending}>
              Save
            </Button>
            <Button variant="secondary" onClick={() => setRenaming(null)}>
              Cancel
            </Button>
          </form>
        )}
        <div className={styles.actions}>
          {active && (
            <Button variant="danger" onClick={() => setConfirming(true)}>
              Cancel
            </Button>
          )}
          {canResume(card.status) && (
            <Button
              variant="secondary"
              disabled={Boolean(notReady) || resume.isPending}
              title={notReady ?? "Continue after the last finished round"}
              onClick={() => resume.mutate()}
            >
              Resume
            </Button>
          )}
          <LinkButton variant="secondary" to={`/new/part?from=${job.id}`}>
            Duplicate
          </LinkButton>
        </div>
      </div>

      <div className={styles.badges}>
        <JobStatusBadge status={card.status} />
        <SimBadge backend={card.sim_backend} />
        {path && (
          <Badge
            tone={path.exploratory ? "warn" : "neutral"}
            label={path.exploratory ? `${path.label}: exploratory` : path.label}
            title={path.exploratory ? CAVEATS.gpuCopies : `Sim path: ${path.detail}`}
          />
        )}
        {card.physical_badge !== "none" && <PhysicalBadge status={card.physical_badge} />}
      </div>

      <KeyValues
        inline
        items={[
          { label: "Part", value: card.part_name ?? "Unknown part" },
          ...(job.plan.poses.length > 1 ? [{ label: "Resting poses", value: posesText(job.plan.poses) }] : []),
          ...(header
            ? [
                { label: "Task", value: taskText(header.task, meta.data) },
                { label: "Camera error", value: errorText(header.error) },
                {
                  label: "Cell profile",
                  value: header.cell_profile_name
                    ? `${header.cell_profile_name}, version ${header.cell_profile_version}`
                    : "Unknown",
                },
              ]
            : []),
          { label: card.finished ? "Finished" : "Started", value: dateTime(card.finished ?? card.created) },
        ]}
      />

      {canResume(card.status) && notReady && (
        <p className={styles.note}>
          Resume needs a ready GPU: {notReady} <Link to="/gpu">Connect a GPU</Link>
        </p>
      )}
      {resume.error && <p className={styles.error}>{resume.error.message}</p>}

      <Tabs
        label="This experiment"
        tabs={[
          { to: `/jobs/${job.id}`, label: card.status === "done" ? "Results" : "Progress", end: true },
          { to: `/jobs/${job.id}/validation`, label: "Validation" },
          { to: `/jobs/${job.id}/log`, label: "Quick logger" },
        ]}
      />

      <ConfirmDialog
        open={confirming && active}
        title={`Cancel ${card.experiment_id}?`}
        confirmLabel="Cancel the experiment"
        cancelLabel="Keep running"
        danger
        pending={cancel.isPending}
        error={cancel.error?.message}
        onConfirm={() => cancel.mutate()}
        onClose={() => setConfirming(false)}
      >
        It stops after the current round. Everything done so far is kept, and Resume continues from there.
      </ConfirmDialog>
    </header>
  );
}
