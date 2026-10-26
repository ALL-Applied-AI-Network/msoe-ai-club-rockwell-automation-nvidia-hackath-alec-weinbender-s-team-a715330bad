import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router";
import { api, unwrapAs, type Schemas } from "../../backend/client";
import { Badge } from "../../components/Badge";
import { SimBadge } from "../../components/Badges";
import { Banner } from "../../components/Banner";
import { Button, LinkButton } from "../../components/Button";
import { Card } from "../../components/Card";
import { NumberInput, TextInput } from "../../components/Field";
import { FingerViewer, type FingerShape } from "../../components/FingerViewer";
import { KeyValues } from "../../components/KeyValues";
import { Modal } from "../../components/Modal";
import { Page } from "../../components/Page";
import { Score } from "../../components/Score";
import { Select } from "../../components/Select";
import { ErrorState, Skeleton } from "../../components/States";
import { Table, type Column } from "../../components/Table";
import { dims, percent } from "../../format";
import { FINGER_FAMILIES, FINGER_SOURCES } from "../../labels";
import styles from "./Fingers.module.css";

type Finger = Schemas["FingerResponse"];
type Geometry = Schemas["FingerGeometryResponse"];
type Qualification = Schemas["QualificationView"];

/** #/fingers/:id: one finger: its shape on the jaw, its details, and every part it was tried on, with the sim's
 *  prediction next to what the robot measured. */
export function FingerDetailPage() {
  const { id = "" } = useParams();
  const geometry = useQuery({
    queryKey: ["fingers", id, "geometry"],
    queryFn: () => unwrapAs<Geometry>(api.GET("/api/fingers/{finger_id}/geometry", { params: { path: { finger_id: id } } })),
  });
  const quals = useQuery({
    queryKey: ["fingers", id, "qualifications"],
    queryFn: () => unwrapAs<Qualification[]>(api.GET("/api/qualifications", { params: { query: { finger_id: id } } })),
  });

  if (geometry.isPending) {
    return (
      <Page title="Finger">
        <Skeleton height={360} />
      </Page>
    );
  }
  if (geometry.isError) {
    return (
      <Page title="Finger">
        <ErrorState title="Couldn't load this finger" message={geometry.error.message} onRetry={() => geometry.refetch()} />
      </Page>
    );
  }
  const finger = geometry.data.finger;

  return (
    <Page
      title={finger.name}
      description={
        finger.source === "stock"
          ? `${finger.code}, the fingers on the ${finger.cell_profile_name}'s robot`
          : `${finger.code}, ${FINGER_SOURCES[finger.source].toLowerCase()} ${FINGER_FAMILIES[finger.family]?.toLowerCase() ?? ""} for the ${finger.cell_profile_name}`
      }
      actions={
        <LinkButton variant="primary" to="/evaluate">
          Evaluate on a part
        </LinkButton>
      }
      rail={<Details finger={finger} />}
      stretch={false}
    >
      {finger.archived && <Banner tone="info">Archived: new evaluations leave it out. Its results stay.</Banner>}
      {finger.source === "generated" && finger.origin_sim_backend === "mock" && (
        <Banner tone="warn">Designed on the mock sim: its shape is real CAD, but the search that chose it was geometry only.</Banner>
      )}
      <Card
        title="On the jaw"
        subtitle={
          finger.source === "stock"
            ? "Both fingers, jaws closed. There's no CAD of the real blades: this is the digital twin's measured model"
            : "Both fingers, jaws closed; the sim mirrors this one for the other jaw"
        }
      >
        <Shape geometry={geometry.data} />
        {finger.warnings.filter((w) => !w.startsWith("placed automatically")).length > 0 && (
          <ul className={styles.list}>
            {finger.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        )}
        {finger.source === "generated" && finger.origin_job_id && (
          <p className={styles.note}>
            Designed by <Link to={`/jobs/${finger.origin_job_id}`}>{finger.origin_label} of its generation job</Link>.
          </p>
        )}
      </Card>
      <Card title="Parts it was tried on" subtitle="The sim's latest prediction for each part, and what the robot measured" flush>
        {quals.isPending ? <Skeleton height={160} /> : <PartsTable rows={quals.data ?? []} />}
      </Card>
    </Page>
  );
}

function Shape({ geometry }: { geometry: Geometry }) {
  const shapes = useMemo<FingerShape[]>(
    () => [{ key: geometry.finger.id, pieces: geometry.geometry.pieces, tone: "finger", mirrored: true }],
    [geometry],
  );
  return <FingerViewer fingers={shapes} label={`${geometry.finger.name}, both fingers with the jaws closed`} height={340} frameKey={geometry.finger.id} />;
}

function PartsTable({ rows }: { rows: Qualification[] }) {
  const [logging, setLogging] = useState<Qualification | null>(null);
  const columns: Column<Qualification>[] = [
    {
      key: "part",
      header: "Part",
      width: "28%",
      render: (q) => (
        <div className={styles.lines}>
          <Link to={`/parts/${q.part_id}`} className={styles.main} title={q.part_name ?? q.part_id}>
            {q.part_name ?? q.part_id}
          </Link>
          {q.prediction && (
            <Link to={`/jobs/${q.prediction.job_id}`} className={styles.sub}>
              {q.prediction.experiment_id}
            </Link>
          )}
        </div>
      ),
    },
    {
      key: "predicted",
      header: "Predicted",
      width: "22%",
      render: (q) =>
        q.prediction ? (
          <Score value={q.prediction.success} sub={q.prediction.sim_backend === "mock" ? <SimBadge backend="mock" /> : undefined} />
        ) : (
          <span className={styles.note}>Not evaluated</span>
        ),
    },
    {
      key: "measured",
      header: "On the robot",
      width: "22%",
      render: (q) =>
        q.measured_success != null ? (
          <div className={styles.lines}>
            <span className={styles.main}>{percent(q.measured_success)}</span>
            <span className={styles.sub}>{q.real_trials} real trials</span>
          </div>
        ) : (
          <span className={styles.note}>Not tested</span>
        ),
    },
    {
      key: "status",
      header: "Status",
      width: "16%",
      render: (q) =>
        q.gap_flagged ? (
          <Badge tone="bad" label="Sim and robot disagree" title="The prediction is outside the 95% interval of what the robot measured." />
        ) : (
          <Badge tone={q.status === "validated" ? "ok" : "neutral"} label={q.status === "validated" ? "Validated" : "Simulated"} />
        ),
    },
    {
      key: "log",
      header: "",
      width: "120px",
      render: (q) => (
        <Button variant="secondary" size="sm" onClick={() => setLogging(q)}>
          Log a session
        </Button>
      ),
    },
  ];
  return (
    <>
      <Table label="Parts it was tried on" columns={columns} rows={rows} rowKey={(q) => String(q.id)} fixed empty="Not tried on any part yet: evaluate it on one." />
      <LogSession qualification={logging} onClose={() => setLogging(null)} />
    </>
  );
}

/** Logs a sitting at the real robot against one finger-and-part pair: trials and successes. */
function LogSession({ qualification, onClose }: { qualification: Qualification | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [trials, setTrials] = useState<number | null>(10);
  const [successes, setSuccesses] = useState<number | null>(null);
  const [kind, setKind] = useState<"natural" | "commanded">("natural");
  const [predicted, setPredicted] = useState<number | null>(null);
  const [operator, setOperator] = useState("");
  const [notes, setNotes] = useState("");
  const log = useMutation({
    mutationFn: () =>
      unwrapAs<Qualification>(
        api.POST("/api/qualifications/{qualification_id}/sessions", {
          params: { path: { qualification_id: qualification!.id } },
          body: {
            trials: trials!,
            successes: successes!,
            kind,
            predicted_success: kind === "commanded" && predicted != null ? predicted / 100 : null,
            operator: operator.trim() || null,
            notes: notes.trim(),
            date: new Date().toISOString().slice(0, 10),
          },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["fingers"] });
      onClose();
    },
  });
  const valid = trials != null && trials >= 1 && successes != null && successes >= 0 && successes <= trials;
  return (
    <Modal
      open={qualification !== null}
      title={qualification ? `Log a session: ${qualification.finger_code} on ${qualification.part_name ?? "the part"}` : "Log a session"}
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={!valid || log.isPending} onClick={() => log.mutate()}>
            Log the session
          </Button>
        </>
      }
    >
      <div className={styles.form}>
        <div className={styles.pair}>
          <NumberInput label="Grasps tried" value={trials} onChange={setTrials} min={1} step={1} />
          <NumberInput label="Grasps held" value={successes} onChange={setSuccesses} min={0} step={1} error={successes != null && trials != null && successes > trials ? "More than were tried" : undefined} />
        </div>
        <Select
          label="How the robot ran"
          value={kind}
          onChange={(event) => setKind(event.target.value as "natural" | "commanded")}
          options={[
            { value: "natural", label: "As the cell runs: compared with the prediction" },
            { value: "commanded", label: "At commanded offsets: compared with the sim at those offsets" },
          ]}
        />
        {kind === "commanded" && (
          <NumberInput label="The sim's rate at those offsets" unit="%" value={predicted} onChange={setPredicted} min={0} max={100} hint="From the test plan's prediction." />
        )}
        <TextInput label="Operator" value={operator} onChange={setOperator} />
        <TextInput label="Notes" value={notes} onChange={setNotes} placeholder="Anything odd about the session" />
        {log.error && <p className={styles.error}>{log.error.message}</p>}
      </div>
    </Modal>
  );
}

/** The finger's details, editable: name, material, friction, quantity, notes; and archiving it. */
function Details({ finger }: { finger: Finger }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(finger.name);
  const [material, setMaterial] = useState(finger.material);
  const [quantity, setQuantity] = useState<number | null>(finger.quantity_on_hand);
  const [notes, setNotes] = useState(finger.notes);
  const save = useMutation({
    mutationFn: (body: Schemas["UpdateFingerRequest"]) =>
      unwrapAs<Finger>(api.PATCH("/api/fingers/{finger_id}", { params: { path: { finger_id: finger.id } }, body })),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["fingers"] }),
  });
  const changed = name !== finger.name || material !== finger.material || quantity !== finger.quantity_on_hand || notes !== finger.notes;
  return (
    <>
      <Card title="Details">
        <KeyValues
          items={[
            { label: "Code", value: finger.code, mono: true },
            { label: "Cell", value: finger.cell_profile_name },
            { label: "Family", value: FINGER_FAMILIES[finger.family] ?? finger.family },
            { label: "Source", value: FINGER_SOURCES[finger.source] },
            ...(finger.extent_mm ? [{ label: "Size", value: dims(finger.extent_mm) }] : []),
            { label: "Pad friction", value: `${finger.pad_friction[0]} static, ${finger.pad_friction[1]} sliding` },
          ]}
        />
      </Card>
      {finger.source !== "stock" && (
        <Card title="Edit">
          <TextInput label="Name" value={name} onChange={setName} />
          <TextInput label="Material" value={material} onChange={setMaterial} />
          <NumberInput label="On hand" value={quantity} onChange={setQuantity} min={0} step={1} />
          <TextInput label="Notes" value={notes} onChange={setNotes} />
          {save.error && <p className={styles.error}>{save.error.message}</p>}
          <div className={styles.buttons}>
            <Button disabled={!changed || !name.trim() || save.isPending} onClick={() => save.mutate({ name, material, quantity_on_hand: quantity ?? 0, notes })}>
              Save
            </Button>
            <Button variant="secondary" disabled={save.isPending} onClick={() => save.mutate({ archived: !finger.archived })}>
              {finger.archived ? "Put back in use" : "Archive"}
            </Button>
          </div>
        </Card>
      )}
    </>
  );
}
