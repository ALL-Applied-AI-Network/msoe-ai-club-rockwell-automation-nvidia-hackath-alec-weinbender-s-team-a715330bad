import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { api, unwrapAs, type Schemas } from "../../backend/client";
import { meshUrl, useMeta, useParts } from "../../backend/queries";
import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Card } from "../../components/Card";
import { FileDrop } from "../../components/FileDrop";
import { FilterBar } from "../../components/FilterBar";
import { Icon } from "../../components/Icon";
import { Menu } from "../../components/Menu";
import { Modal } from "../../components/Modal";
import { Page } from "../../components/Page";
import { weakGrip } from "../../components/PartForm";
import { PartUpload } from "../../components/PartUpload";
import { PartViewer } from "../../components/PartViewer";
import { SearchInput } from "../../components/SearchInput";
import { Segmented } from "../../components/Segmented";
import { Select } from "../../components/Select";
import { ErrorState, Skeleton } from "../../components/States";
import { Table, type Column } from "../../components/Table";
import { dims, mass } from "../../format";
import styles from "./PartsLibraryPage.module.css";

type Part = Schemas["PartResponse"];
type Intake = Schemas["IntakeResponse"];
type Status = "all" | "ready";

/** #/parts: every uploaded part, ready to evaluate against the finger library or to design a finger for. `?upload=1`
 *  opens the upload. */
export function PartsLibraryPage() {
  const parts = useParts();
  const meta = useMeta();
  const [params, setParams] = useSearchParams();
  const [status, setStatus] = useState<Status>("all");
  const [material, setMaterial] = useState("");
  const [query, setQuery] = useState("");
  const uploading = params.get("upload") === "1";
  const setUploading = (open: boolean) => setParams(open ? { upload: "1" } : {}, { replace: true });

  const q = query.trim().toLowerCase();
  const found = (parts.data ?? []).filter(
    (p) => (!material || p.material === material) && (!q || [p.name, p.part_number ?? ""].some((t) => t.toLowerCase().includes(q))),
  );
  const shown = found.filter((p) => status === "all" || p.intake_status === status);
  const count = (s: Status) => found.filter((p) => s === "all" || p.intake_status === s).length;

  return (
    <Page
      title="Part Library"
      description="Every part you've uploaded, ready to evaluate against the finger library"
      actions={
        <Button onClick={() => setUploading(true)}>
          <Icon name="upload" />
          Upload parts
        </Button>
      }
    >
      <FilterBar
        chips={
          <Segmented
            label="Status"
            value={status}
            onChange={setStatus}
            options={[
              { value: "all", label: "All", count: count("all") },
              { value: "ready", label: "Ready", count: count("ready") },
            ]}
          />
        }
      >
        <Select
          label="Material"
          inline
          value={material}
          onChange={(event) => setMaterial(event.target.value)}
          options={[{ value: "", label: "All materials" }, ...(meta.data?.materials ?? []).map((m) => ({ value: m.name, label: m.label }))]}
        />
        <SearchInput value={query} onChange={setQuery} placeholder="Search by part number or name" />
      </FilterBar>

      {parts.isPending && <Skeleton height={320} />}
      {parts.isError && <ErrorState title="Couldn't load the parts" message={parts.error.message} onRetry={() => parts.refetch()} />}
      {parts.isSuccess && (
        <Card title="Parts" subtitle={`${shown.length} shown`} flush>
          <PartTable parts={shown} />
        </Card>
      )}

      <UploadParts open={uploading} onClose={() => setUploading(false)} />
    </Page>
  );
}

function PartTable({ parts }: { parts: Part[] }) {
  const meta = useMeta();
  const materialLabel = (p: Part) => (p.material ? (meta.data?.materials.find((m) => m.name === p.material)?.label ?? p.material) : null);
  const columns: Column<Part>[] = [
    {
      key: "part",
      header: "Part",
      width: "34%",
      render: (p) => (
        <div className={styles.part}>
          <PartViewer mode="icon" url={meshUrl(p.id)} label={p.name} />
          <div className={styles.lines}>
            <Link to={`/parts/${p.id}`} className={styles.main} title={p.part_number ?? p.name}>
              {p.part_number ?? p.name}
            </Link>
            <span className={styles.sub}>{p.part_number ? p.name : p.pose?.label ?? "No resting pose chosen"}</span>
          </div>
        </div>
      ),
    },
    { key: "size", header: "Size", width: "20%", render: (p) => <span className={styles.main}>{dims(p.extent_mm)}</span> },
    {
      key: "material",
      header: "Material",
      width: "20%",
      render: (p) => (
        <div className={styles.lines}>
          <span className={styles.main}>{materialLabel(p) ?? "Not set"}</span>
          <span className={styles.sub}>{p.confirmed_mass_g != null ? mass(p.confirmed_mass_g, p.mass_unit) : "No mass yet"}</span>
        </div>
      ),
    },
    {
      key: "status",
      header: "Status",
      width: "20%",
      render: (p) => (
        <div className={styles.badges}>
          {p.intake_status === "ready" ? <Badge tone="ok" label="Ready" /> : <Badge tone="warn" label="Needs a material" />}
          {p.fragile && <Badge tone="warn" label="Fragile" />}
          {weakGrip(p) && <Badge tone="warn" label="Weak grip" title="Heavy or slippery: the twin may drop it for every finger." />}
        </div>
      ),
    },
    {
      key: "menu",
      header: "",
      width: "44px",
      render: (p) => (
        <Menu
          label={`More for ${p.name}`}
          items={[
            { label: "Open", to: `/parts/${p.id}` },
            { label: "Evaluate the finger library", to: `/evaluate?part=${p.id}` },
            { label: "Generate a finger", to: `/new/pose?part=${p.id}` },
          ]}
        />
      ),
    },
  ];
  return <Table label="Parts" columns={columns} rows={parts} rowKey={(p) => p.id} fixed empty="No parts match these filters." />;
}

/** Uploads parts: one file (then its page), several at once, or a whole folder. Each file of a batch is stored on its
 *  own, and the report says which were read, which need a material, and which couldn't be read. */
function UploadParts({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<"one" | "many" | "folder">("one");
  const [units, setUnits] = useState<"mm" | "in">("mm");
  const batch = useMutation({
    mutationFn: (files: File[]) =>
      unwrapAs<Intake[]>(
        api.POST("/api/parts/batch", {
          // The schema calls the files strings; they're sent as multipart form data.
          body: { files: files as unknown as string[], units },
          bodySerializer: (body) => {
            const data = new FormData();
            for (const file of body.files as unknown as File[]) data.append("files", file);
            data.append("units", units);
            return data;
          },
        }),
      ),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["parts"] }),
  });
  const close = () => {
    batch.reset();
    onClose();
  };

  return (
    <Modal open={open} title="Upload parts" onClose={close} wide>
      <div className={styles.upload}>
        <Segmented
          label="What to upload"
          value={mode}
          onChange={(value) => {
            batch.reset();
            setMode(value);
          }}
          options={[
            { value: "one", label: "One file" },
            { value: "many", label: "Several files" },
            { value: "folder", label: "A folder" },
          ]}
        />
        {mode === "one" ? (
          <PartUpload
            onUploaded={(part) => {
              close();
              navigate(`/parts/${part.id}`);
            }}
          />
        ) : (
          <>
            <Select
              label="Units of any STL files"
              value={units}
              onChange={(event) => setUnits(event.target.value as "mm" | "in")}
              options={[
                { value: "mm", label: "Millimetres" },
                { value: "in", label: "Inches" },
              ]}
            />
            <FileDrop
              label={mode === "folder" ? "Drop the files of a folder here" : "Drop STEP or STL files here"}
              accept=".step,.stp,.stl"
              folder={mode === "folder"}
              busy={batch.isPending ? "Reading the parts" : undefined}
              error={batch.error?.message}
              hint="Files that aren't STEP or STL are skipped. Up to 50 parts at a time."
              onFiles={(files) => batch.mutate(files)}
            />
            {batch.data && <IntakeReport rows={batch.data} />}
          </>
        )}
      </div>
    </Modal>
  );
}

const INTAKE = {
  ready: { tone: "ok", label: "Ready" },
  needs_properties: { tone: "warn", label: "Needs a material" },
  file_error: { tone: "bad", label: "Couldn't read it" },
  skipped: { tone: "neutral", label: "Skipped" },
} as const;

function IntakeReport({ rows }: { rows: Intake[] }) {
  const columns: Column<Intake>[] = [
    {
      key: "file",
      header: "File",
      width: "45%",
      render: (r) =>
        r.part ? (
          <Link to={`/parts/${r.part.id}`} className={styles.main}>
            {r.filename}
          </Link>
        ) : (
          <span className={styles.main}>{r.filename}</span>
        ),
    },
    { key: "status", header: "Status", width: "25%", render: (r) => <Badge {...INTAKE[r.status]} /> },
    { key: "why", header: "Note", width: "30%", render: (r) => <span className={styles.sub} title={r.reason ?? undefined}>{r.reason ?? ""}</span> },
  ];
  const stored = rows.filter((r) => r.part).length;
  return (
    <div className={styles.report}>
      <p className={styles.sub}>
        {stored} of {rows.length} files stored. Parts that need a material can't be evaluated until it's set.
      </p>
      <Table label="Upload report" columns={columns} rows={rows} rowKey={(r) => r.filename} fixed />
    </div>
  );
}
