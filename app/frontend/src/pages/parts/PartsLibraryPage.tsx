import { useState } from "react";
import { Link, useNavigate } from "react-router";
import type { Schemas } from "../../backend/client";
import { useMeta } from "../../backend/queries";
import { Badge } from "../../components/Badge";
import { Button, LinkButton } from "../../components/Button";
import { Card } from "../../components/Card";
import { Icon } from "../../components/Icon";
import { KeyValues } from "../../components/KeyValues";
import { Modal } from "../../components/Modal";
import { Page } from "../../components/Page";
import { weakGrip } from "../../components/PartForm";
import { PartUpload } from "../../components/PartUpload";
import { PartViewer } from "../../components/PartViewer";
import { EmptyState, ErrorState, Skeleton } from "../../components/States";
import { dims, mass, timeAgo } from "../../format";
import { meshUrl, useParts } from "../../backend/queries";
import styles from "./PartsLibraryPage.module.css";

type Part = Schemas["PartResponse"];

/** #/parts: every uploaded part, ready to reuse in a new experiment. */
export function PartsLibraryPage() {
  const parts = useParts();
  const navigate = useNavigate();
  const [uploading, setUploading] = useState(false);
  const upload = (
    <Button onClick={() => setUploading(true)}>
      <Icon name="upload" />
      Upload a part
    </Button>
  );

  return (
    <Page
      title="Parts"
      description="Every part you've uploaded, measured and ready to reuse. Open one to check its size and set its material and mass."
      actions={upload}
    >
      {parts.isPending && (
        <div className={styles.grid}>
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} height={380} />
          ))}
        </div>
      )}
      {parts.isError && <ErrorState title="Couldn't load the parts" message={parts.error.message} onRetry={() => parts.refetch()} />}
      {parts.isSuccess && parts.data.length === 0 && (
        <EmptyState title="No parts yet" action={upload}>
          Upload a STEP or STL of the part to pick. It's measured and split into convex pieces once, then any experiment
          can use it.
        </EmptyState>
      )}
      {parts.isSuccess && parts.data.length > 0 && (
        <div className={styles.grid}>
          {parts.data.map((part) => (
            <PartCard key={part.id} part={part} />
          ))}
        </div>
      )}

      <Modal open={uploading} title="Upload a part" onClose={() => setUploading(false)}>
        <PartUpload
          onUploaded={(part) => {
            setUploading(false);
            navigate(`/parts/${part.id}`);
          }}
        />
      </Modal>
    </Page>
  );
}

function PartCard({ part }: { part: Part }) {
  const meta = useMeta();
  const material = part.material ? (meta.data?.materials.find((m) => m.name === part.material)?.label ?? part.material) : null;
  return (
    <Card
      title={<Link to={`/parts/${part.id}`}>{part.name}</Link>}
      subtitle={part.source === "stl" ? `STL file, read in ${part.units === "in" ? "inches" : "millimetres"}` : "STEP file"}
      aside={
        <>
          {part.fragile && <Badge tone="warn" label="Fragile" />}
          {weakGrip(part) && <Badge tone="warn" label="Weak grip" title="Heavy or slippery: the twin may drop it for every design." />}
        </>
      }
      footer={
        <>
          <span className={styles.time}>Uploaded {timeAgo(part.created)}</span>
          <div className={styles.actions}>
            <LinkButton variant="ghost" size="sm" to={`/new/pose?part=${part.id}`}>
              New experiment with this part
            </LinkButton>
            <LinkButton size="sm" to={`/parts/${part.id}`}>
              Open
            </LinkButton>
          </div>
        </>
      }
    >
      <Link to={`/parts/${part.id}`} tabIndex={-1}>
        <PartViewer mode="thumbnail" url={meshUrl(part.id)} label={`${part.name}, ${part.pose?.label ?? "as in the CAD file"}`} />
      </Link>
      <KeyValues
        items={[
          { label: "Size", value: dims(part.extent_mm) },
          { label: "Resting", value: part.pose?.label ?? "As in the CAD file" },
          { label: "Material", value: material ?? "Not set yet" },
          {
            label: "Mass",
            value:
              part.confirmed_mass_g != null
                ? `${mass(part.confirmed_mass_g, part.mass_unit)}, ${part.mass_source === "measured" ? "measured" : "computed"}`
                : "Not known yet",
          },
        ]}
      />
    </Card>
  );
}
