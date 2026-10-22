import { useParams } from "react-router";
import { LinkButton } from "../../components/Button";
import { Card } from "../../components/Card";
import { KeyValues } from "../../components/KeyValues";
import { Page } from "../../components/Page";
import { PartForm } from "../../components/PartForm";
import { PartViewer } from "../../components/PartViewer";
import { Stat } from "../../components/Stat";
import { ErrorState, Skeleton } from "../../components/States";
import { dateTime, dims, quantity } from "../../format";
import { meshUrl, usePart } from "../../backend/queries";
import styles from "./PartDetailPage.module.css";

/** #/parts/:id: one part. Its size comes first and large, because that's where a units mistake shows (a 10 mm cube
 *  read as 254 mm); then its 3D view, and the material, mass and handling to confirm. */
export function PartDetailPage() {
  const { id = "" } = useParams();
  const part = usePart(id);
  const newExperiment = (
    <LinkButton variant="primary" to={`/new/pose?part=${id}`}>
      New experiment with this part
    </LinkButton>
  );

  if (part.isPending) {
    return (
      <Page title="Part">
        <Skeleton height={480} />
      </Page>
    );
  }
  if (part.isError) {
    return (
      <Page title="Part">
        <ErrorState title="Couldn't load the part" message={part.error.message} onRetry={() => part.refetch()} />
      </Page>
    );
  }

  const p = part.data;
  const [x, y, z] = p.extent_mm;
  return (
    <Page
      title={p.name}
      description={`${p.source === "stl" ? `STL file, read in ${p.units === "in" ? "inches" : "millimetres"}` : "STEP file"}, uploaded ${dateTime(p.created)}`}
      actions={
        <>
          <LinkButton to="/parts">All parts</LinkButton>
          {newExperiment}
        </>
      }
    >
      <div className={styles.layout}>
        <div className={styles.column}>
          <Card title="Size">
            <Stat size="lg" label="Bounding box" value={dims(p.extent_mm)} detail={`x ${quantity(x, "mm", 1)}, y ${quantity(y, "mm", 1)}, z ${quantity(z, "mm", 1)}, as in the CAD file`} />
            <p className={styles.note}>
              Check it against the real part. A size 25.4 times too big or too small means the file's units were read
              wrong: upload it again{p.source === "stl" ? " and choose the other units" : ""}.
            </p>
          </Card>
          <Card title="3D view" subtitle={`Resting ${p.pose?.label ?? "as in the CAD file"}`}>
            <PartViewer url={meshUrl(p.id)} label={`${p.name}, ${p.pose?.label ?? "as in the CAD file"}`} height={380} />
            <KeyValues
              items={[
                { label: "Volume", value: quantity(p.measured.volume_mm3 / 1000, "cm³") },
                { label: "Closest simple shape", value: p.measured.fit },
                { label: "Convex pieces", value: String(p.n_pieces) },
              ]}
            />
          </Card>
        </div>
        <Card title="Material and handling" subtitle="What the sim needs to know about the part. Only what you change is saved.">
          <PartForm key={p.id} part={p} />
        </Card>
      </div>
    </Page>
  );
}
