import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { api, unwrap, type Schemas } from "../../backend/client";
import { Badge } from "../../components/Badge";
import { Button, LinkButton } from "../../components/Button";
import { Card } from "../../components/Card";
import { Icon } from "../../components/Icon";
import { KeyValues } from "../../components/KeyValues";
import { Page } from "../../components/Page";
import { EmptyState, ErrorState, Skeleton } from "../../components/States";
import { CAVEATS } from "../../caveats";
import { count, dateTime, mm } from "../../format";
import { NewProfileModal } from "./NewProfileModal";
import { placeholders } from "./profileFields";
import styles from "./Cells.module.css";

type Saved = Schemas["CellProfileResponse"];

/** #/cells: every cell, at its profile's latest version. A job records the exact version it ran with, so editing
 *  one here never changes a finished job. */
export function CellProfilesSection() {
  const profiles = useQuery({
    queryKey: ["cell-profiles"],
    // openapi-fetch types responses with tuples widened to arrays; the data is the schema's, so it's typed as that
    queryFn: async () => (await unwrap(api.GET("/api/cell-profiles"))) as Saved[],
  });
  const [copyFrom, setCopyFrom] = useState<Saved | null | undefined>(undefined); // undefined: the dialog is closed

  return (
    <Page
      title="Cells"
      actions={
        <Button onClick={() => setCopyFrom(profiles.data?.[0] ?? null)} disabled={!profiles.data}>
          <Icon name="plus" />
          New cell
        </Button>
      }
    >

      {profiles.isPending && (
        <div className={styles.grid}>
          <Skeleton height={240} />
          <Skeleton height={240} />
        </div>
      )}
      {profiles.isError && (
        <ErrorState title="Couldn't load the cells" message={profiles.error.message} onRetry={() => profiles.refetch()} />
      )}
      {profiles.data?.length === 0 && (
        <EmptyState title="No cells yet">Restart the API to create the default one.</EmptyState>
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
    </Page>
  );
}

function ProfileCard({ saved, onCopy }: { saved: Saved; onCopy: () => void }) {
  const { profile, twin_mismatches: mismatches } = saved;
  const toConfirm = placeholders(profile);
  return (
    <Card
      title={<Link to={`/cells/${saved.id}`}>{saved.name}</Link>}
      subtitle={`Version ${saved.version}, ${dateTime(saved.created)}`}
      aside={
        <>
          {toConfirm.size > 0 && (
            <Badge tone="warn" label={count(toConfirm.size, "placeholder", "placeholders")} title={CAVEATS.placeholderCell} />
          )}
          {mismatches.length ? (
            <Badge tone="warn" label="Differs from the twin" title={`${CAVEATS.twinMismatch} ${mismatches.join("; ")}`} />
          ) : (
            <Badge tone="ok" label="Matches the twin" title="The sim models this cell's gripper." />
          )}
        </>
      }
      footer={
        <div className={styles.actions}>
          <Button variant="ghost" size="sm" onClick={onCopy}>
            Duplicate
          </Button>
          <LinkButton variant="secondary" size="sm" to={`/cells/${saved.id}`}>
            Edit
          </LinkButton>
        </div>
      }
    >
      <KeyValues
        items={[
          { label: "Robot", value: profile.robot_model },
          { label: "Gripper", value: profile.gripper_model },
          { label: "Stroke per jaw", value: mm(profile.stroke_per_jaw_mm) },
          { label: "Stock fingers", value: profile.stock_fingers },
        ]}
      />
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
