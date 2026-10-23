import { useState } from "react";
import { Link, useNavigate } from "react-router";
import type { Schemas } from "../../backend/client";
import { useMeta } from "../../backend/queries";
import { Badge } from "../../components/Badge";
import { Button, LinkButton } from "../../components/Button";
import { Icon } from "../../components/Icon";
import { Modal } from "../../components/Modal";
import { Page } from "../../components/Page";
import { weakGrip } from "../../components/PartForm";
import { PartUpload } from "../../components/PartUpload";
import { PartViewer } from "../../components/PartViewer";
import { EmptyState, ErrorState, Skeleton } from "../../components/States";
import { dims, mass } from "../../format";
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
      actions={upload}
    >
      {parts.isPending && (
        <div className={styles.grid}>
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} height={250} />
          ))}
        </div>
      )}
      {parts.isError && <ErrorState title="Couldn't load the parts" message={parts.error.message} onRetry={() => parts.refetch()} />}
      {parts.isSuccess && parts.data.length === 0 && (
        <EmptyState title="No parts yet" action={upload}>
          Upload a STEP or STL file to start.
        </EmptyState>
      )}
      {parts.isSuccess && parts.data.length > 0 && (
        <div className={styles.grid}>
          {parts.data.map((part) => (
            <PartTile key={part.id} part={part} />
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

/** One part as a tile: the whole tile opens the part; starting an experiment with it is the one other action. */
function PartTile({ part }: { part: Part }) {
  const meta = useMeta();
  const material = part.material ? (meta.data?.materials.find((m) => m.name === part.material)?.label ?? part.material) : null;
  const weight = part.confirmed_mass_g != null ? mass(part.confirmed_mass_g, part.mass_unit) : null;
  return (
    <article className={styles.tile}>
      <Link to={`/parts/${part.id}`} className={styles.open}>
        <PartViewer mode="thumbnail" url={meshUrl(part.id)} label={`${part.name}, ${part.pose?.label ?? "as in the CAD file"}`} />
        <span className={styles.name}>{part.name}</span>
        <span className={styles.size}>{dims(part.extent_mm)}</span>
        <span className={styles.facts}>
          {material ?? "No material"}, {weight ?? "no mass"}
        </span>
      </Link>
      <div className={styles.foot}>
        {part.fragile && <Badge tone="warn" label="Fragile" />}
        {weakGrip(part) && <Badge tone="warn" label="Weak grip" title="Heavy or slippery: the twin may drop it for every design." />}
        <LinkButton variant="ghost" size="sm" className={styles.start} to={`/new/pose?part=${part.id}`}>
          New experiment
        </LinkButton>
      </div>
    </article>
  );
}
