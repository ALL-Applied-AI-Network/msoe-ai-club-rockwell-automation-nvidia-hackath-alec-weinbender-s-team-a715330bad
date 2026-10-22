import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { api, unwrap, type Schemas } from "../../backend/client";
import { Badge } from "../../components/Badge";
import { Button, LinkButton } from "../../components/Button";
import { Card } from "../../components/Card";
import { Icon } from "../../components/Icon";
import { KeyValues } from "../../components/KeyValues";
import { EmptyState, ErrorState, Skeleton } from "../../components/States";
import { CAVEATS } from "../../caveats";
import { count, dateTime, mm } from "../../format";
import { NewProfileModal } from "./NewProfileModal";
import { placeholders } from "./profileFields";
import styles from "./Settings.module.css";

type Saved = Schemas["CellProfileResponse"];

/** #/settings/cells: every cell profile, at its latest version. A job records the exact version it ran with, so editing
 *  one here never changes a finished job. */
export function CellProfilesSection() {
  const profiles = useQuery({
    queryKey: ["cell-profiles"],
    // openapi-fetch types responses with tuples widened to arrays; the data is the schema's, so it's typed as that
    queryFn: async () => (await unwrap(api.GET("/api/cell-profiles"))) as Saved[],
  });
  const [copyFrom, setCopyFrom] = useState<Saved | null | undefined>(undefined); // undefined: the dialog is closed

  return (
    <div className={styles.section}>
      <div className={styles.toolbar}>
        <p className={styles.lead}>
          A cell profile describes one robot, gripper and cell. Saving an edit makes a new version; old versions never change.
        </p>
        <Button onClick={() => setCopyFrom(profiles.data?.[0] ?? null)} disabled={!profiles.data}>
          <Icon name="plus" />
          New profile
        </Button>
      </div>

      {profiles.isPending && (
        <div className={styles.grid}>
          <Skeleton height={240} />
          <Skeleton height={240} />
        </div>
      )}
      {profiles.isError && (
        <ErrorState title="Couldn't load the cell profiles" message={profiles.error.message} onRetry={() => profiles.refetch()} />
      )}
      {profiles.data?.length === 0 && (
        <EmptyState title="No cell profiles yet">The API makes the default UWM CSI cell profile when it starts.</EmptyState>
      )}
      {profiles.data && profiles.data.length > 0 && (
        <div className={styles.grid}>
          {profiles.data.map((saved) => (
            <ProfileCard key={saved.id} saved={saved} onCopy={() => setCopyFrom(saved)} />
          ))}
        </div>
      )}

      {profiles.data && (
        <NewProfileModal
          open={copyFrom !== undefined}
          profiles={profiles.data}
          initial={copyFrom ?? undefined}
          onClose={() => setCopyFrom(undefined)}
        />
      )}
    </div>
  );
}

function ProfileCard({ saved, onCopy }: { saved: Saved; onCopy: () => void }) {
  const { profile, twin_mismatches: mismatches } = saved;
  const toConfirm = placeholders(profile);
  return (
    <Card
      title={<Link to={`/settings/cells/${saved.id}`}>{saved.name}</Link>}
      subtitle={`Version ${saved.version}, saved ${dateTime(saved.created)}`}
      aside={
        mismatches.length ? (
          <Badge tone="warn" label="Differs from the twin" title={`${CAVEATS.twinMismatch} ${mismatches.join("; ")}`} />
        ) : (
          <Badge tone="ok" label="Matches the twin" title="The sim models this cell's gripper." />
        )
      }
      footer={
        <div className={styles.actions}>
          <Button variant="ghost" size="sm" onClick={onCopy}>
            New profile from this one
          </Button>
          <LinkButton variant="secondary" size="sm" to={`/settings/cells/${saved.id}`}>
            Edit
          </LinkButton>
        </div>
      }
    >
      <KeyValues
        items={[
          { label: "Robot", value: profile.robot_model },
          { label: "Gripper", value: profile.gripper_model, placeholder: toConfirm.has("gripper_model") },
          { label: "Stroke per jaw", value: mm(profile.stroke_per_jaw_mm), placeholder: toConfirm.has("stroke_per_jaw_mm") },
          { label: "Stock fingers", value: profile.stock_fingers },
        ]}
      />
      <div className={styles.badges}>
        {toConfirm.size > 0 ? (
          <Badge tone="warn" label={`${count(toConfirm.size, "placeholder field", "placeholder fields")}`} title={CAVEATS.placeholderCell} />
        ) : (
          <Badge tone="ok" label="Every field measured" />
        )}
      </div>
      {mismatches.length > 0 && (
        <div>
          <p className={styles.note}>{CAVEATS.twinMismatch}</p>
          <ul className={styles.list}>
            {mismatches.map((m) => (
              <li key={m}>{m}</li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  );
}
