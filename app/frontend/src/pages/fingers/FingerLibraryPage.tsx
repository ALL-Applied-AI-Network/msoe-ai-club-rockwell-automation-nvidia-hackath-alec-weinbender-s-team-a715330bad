import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { api, unwrapAs, type Schemas } from "../../backend/client";
import { useCellProfiles, useFingers } from "../../backend/queries";
import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Card } from "../../components/Card";
import { FilterBar } from "../../components/FilterBar";
import { Checkbox, NumberInput, TextInput } from "../../components/Field";
import { FileDrop } from "../../components/FileDrop";
import { FingerIcon } from "../../components/FingerViewer";
import { Icon } from "../../components/Icon";
import { Menu } from "../../components/Menu";
import { Modal } from "../../components/Modal";
import { Page } from "../../components/Page";
import { Score } from "../../components/Score";
import { SearchInput } from "../../components/SearchInput";
import { Segmented } from "../../components/Segmented";
import { Select } from "../../components/Select";
import { ErrorState, Skeleton } from "../../components/States";
import { Table, type Column } from "../../components/Table";
import { FINGER_FAMILIES, FINGER_SOURCES } from "../../labels";
import styles from "./Fingers.module.css";

type Finger = Schemas["FingerResponse"];
type Source = Finger["source"];

/** #/fingers: the fingers the cells can use, where each has been tried and how it did. Evaluation jobs try them on new
 *  parts; a generation job's design joins from its results page. */
export function FingerLibraryPage() {
  const fingers = useFingers();
  const cells = useCellProfiles();
  const [source, setSource] = useState<"all" | Source>("all");
  const [cell, setCell] = useState("");
  const [archived, setArchived] = useState(false);
  const [query, setQuery] = useState("");
  const [uploading, setUploading] = useState(false);

  const all = (fingers.data ?? []).filter((f) => f.archived === archived && (!cell || f.cell_profile_name === cell));
  const q = query.trim().toLowerCase();
  const found = all.filter((f) => !q || [f.code, f.name, f.material, FINGER_FAMILIES[f.family]].some((t) => t.toLowerCase().includes(q)));
  const shown = found.filter((f) => source === "all" || f.source === source);
  const count = (s: "all" | Source) => found.filter((f) => s === "all" || f.source === s).length;

  return (
    <Page
      title="Finger Library"
      description="The fingers your cells can use, and how each did on the parts it was tried on"
      actions={
        <Button onClick={() => setUploading(true)}>
          <Icon name="upload" />
          Upload a finger
        </Button>
      }
    >
      <FilterBar
        chips={
          <Segmented
            label="Source"
            value={source}
            onChange={setSource}
            options={[
              { value: "all", label: "All", count: count("all") },
              { value: "stock", label: "Installed", count: count("stock") },
              { value: "generated", label: "Generated", count: count("generated") },
              { value: "uploaded", label: "Uploaded", count: count("uploaded") },
            ]}
          />
        }
      >
        <Select
          label="Cell"
          inline
          value={cell}
          onChange={(event) => setCell(event.target.value)}
          options={[{ value: "", label: "All cells" }, ...(cells.data ?? []).map((c) => ({ value: c.name, label: c.name }))]}
        />
        <Select
          label="In use or archived"
          inline
          value={archived ? "archived" : ""}
          onChange={(event) => setArchived(event.target.value === "archived")}
          options={[
            { value: "", label: "In use" },
            { value: "archived", label: "Archived" },
          ]}
        />
        <SearchInput value={query} onChange={setQuery} placeholder="Search by code, name or material" />
      </FilterBar>

      {fingers.isPending && <Skeleton height={320} />}
      {fingers.isError && <ErrorState title="Couldn't load the library" message={fingers.error.message} onRetry={() => fingers.refetch()} />}
      {fingers.isSuccess && (
        <Card title={archived ? "Archived fingers" : "Fingers"} subtitle={`${shown.length} shown`} flush>
          <FingerTable fingers={shown} />
        </Card>
      )}

      <UploadFinger open={uploading} onClose={() => setUploading(false)} />
    </Page>
  );
}

function FingerTable({ fingers }: { fingers: Finger[] }) {
  const queryClient = useQueryClient();
  const archive = useMutation({
    mutationFn: (f: Finger) =>
      unwrapAs<Finger>(api.PATCH("/api/fingers/{finger_id}", { params: { path: { finger_id: f.id } }, body: { archived: !f.archived } })),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["fingers"] }),
  });
  const columns: Column<Finger>[] = [
    {
      key: "finger",
      header: "Finger",
      width: "30%",
      render: (f) => (
        <div className={styles.finger}>
          <FingerIcon fingerId={f.id} label={`${f.name}, both fingers with the jaws closed`} />
          <div className={styles.lines}>
            <Link to={`/fingers/${f.id}`} className={styles.main} title={f.name}>
              {f.name}
            </Link>
            <span className={styles.sub}>
              <code>{f.code}</code> {f.cell_profile_name}
            </span>
          </div>
        </div>
      ),
    },
    {
      key: "kind",
      header: "Family",
      width: "14%",
      render: (f) => (
        <div className={styles.lines}>
          <span className={styles.main}>{FINGER_FAMILIES[f.family] ?? f.family}</span>
          <span className={styles.sub}>{f.source === "stock" ? "Measured, no CAD" : FINGER_SOURCES[f.source]}</span>
        </div>
      ),
    },
    {
      key: "material",
      header: "Material",
      width: "17%",
      render: (f) => (
        <div className={styles.lines}>
          <span className={styles.main}>{f.material}</span>
          <span className={styles.sub}>{f.source === "stock" ? "On the robot" : `${f.quantity_on_hand} on hand`}</span>
        </div>
      ),
    },
    {
      key: "tried",
      header: "Tried on",
      width: "15%",
      render: (f) => (
        <div className={styles.lines}>
          <span className={styles.main}>{f.parts_evaluated === 1 ? "1 part" : `${f.parts_evaluated} parts`}</span>
          <span className={styles.sub}>{f.validated_parts > 0 ? `${f.validated_parts} validated on the robot` : "Not on the robot yet"}</span>
        </div>
      ),
    },
    { key: "best", header: "Best predicted", width: "16%", render: (f) => <Score value={f.best_success} /> },
    {
      key: "menu",
      header: "",
      width: "44px",
      render: (f) => (
        <Menu
          label={`More for ${f.code}`}
          items={[
            { label: "Open", to: `/fingers/${f.id}` },
            ...(f.source === "stock" ? [] : [{ label: f.archived ? "Put back in use" : "Archive", onSelect: () => archive.mutate(f) }]),
          ]}
        />
      ),
    },
  ];
  return <Table label="Fingers" columns={columns} rows={fingers} rowKey={(f) => f.id} fixed empty="No fingers match these filters." />;
}

type Form = {
  file: File | null;
  cell: number | null;
  units: "mm" | "in";
  name: string;
  family: string;
  material: string;
  quantity: number | null;
  mirror: boolean;
  upsideDown: boolean;
};

/** Registers a finger the factory owns from its CAD. The app places it on the jaw (check the preview after), and every
 *  evaluation on its cell tries it from then on. */
function UploadFinger({ open, onClose }: { open: boolean; onClose: () => void }) {
  const cells = useCellProfiles();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [form, setForm] = useState<Form>({ file: null, cell: null, units: "mm", name: "", family: "flat", material: "PLA", quantity: 1, mirror: false, upsideDown: false });
  const set = (patch: Partial<Form>) => setForm((f) => ({ ...f, ...patch }));
  const cellId = form.cell ?? cells.data?.[0]?.id ?? null;
  const stl = form.file?.name.toLowerCase().endsWith(".stl") ?? false;
  const upload = useMutation({
    mutationFn: () =>
      unwrapAs<Finger>(
        api.POST("/api/fingers", {
          // The schema calls the file a string; it's sent as multipart form data.
          body: {
            finger_file: form.file as unknown as string,
            cell_profile_id: cellId!,
            units: stl ? form.units : null,
            name: form.name.trim() || null,
            family: form.family as Finger["family"],
            material: form.material,
            quantity_on_hand: form.quantity ?? 0,
            notes: "",
            mirror: form.mirror,
            upside_down: form.upsideDown,
          },
          bodySerializer: (body) => {
            const data = new FormData();
            for (const [key, value] of Object.entries(body)) {
              if (value == null) continue;
              data.append(key, key === "finger_file" ? (value as unknown as File) : String(value));
            }
            return data;
          },
        }),
      ),
    onSuccess: (finger) => {
      void queryClient.invalidateQueries({ queryKey: ["fingers"] });
      onClose();
      navigate(`/fingers/${finger.id}`);
    },
  });

  return (
    <Modal
      open={open}
      title="Upload a finger"
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={!form.file || cellId == null || upload.isPending} onClick={() => upload.mutate()}>
            {upload.isPending ? "Uploading" : "Add to the library"}
          </Button>
        </>
      }
    >
      <div className={styles.form}>
        <FileDrop
          label={form.file ? form.file.name : "Drop one finger's STEP or STL here"}
          accept=".step,.stp,.stl"
          error={upload.error?.message}
          hint="One finger: the sim mirrors it for the other jaw."
          onFile={(file) => set({ file, name: form.name || file.name.replace(/\.[^.]+$/, "") })}
        />
        <div className={styles.pair}>
          <Select
            label="Cell it fits"
            value={String(cellId ?? "")}
            onChange={(event) => set({ cell: Number(event.target.value) })}
            options={(cells.data ?? []).map((c) => ({ value: String(c.id), label: c.name }))}
          />
          {stl && (
            <Select
              label="Units of the STL"
              value={form.units}
              onChange={(event) => set({ units: event.target.value as "mm" | "in" })}
              options={[
                { value: "mm", label: "Millimetres" },
                { value: "in", label: "Inches" },
              ]}
            />
          )}
        </div>
        <TextInput label="Name" value={form.name} onChange={(name) => set({ name })} placeholder="The file's name" />
        <div className={styles.pair}>
          <Select
            label="Family"
            value={form.family}
            onChange={(event) => set({ family: event.target.value })}
            options={["flat", "vpad", "imprint", "other"].map((value) => ({ value, label: FINGER_FAMILIES[value] }))}
          />
          <TextInput label="Material" value={form.material} onChange={(material) => set({ material })} />
          <NumberInput label="On hand" value={form.quantity} onChange={(quantity) => set({ quantity })} min={0} step={1} />
        </div>
        <Checkbox label="Its gripping face points the other way in the file" checked={form.mirror} onChange={(mirror) => set({ mirror })} />
        <Checkbox label="Its fingertips point up in the file" checked={form.upsideDown} onChange={(upsideDown) => set({ upsideDown })} />
        <Badge tone="neutral" label="The app places it on the jaw: check the 3D view after" />
      </div>
    </Modal>
  );
}
