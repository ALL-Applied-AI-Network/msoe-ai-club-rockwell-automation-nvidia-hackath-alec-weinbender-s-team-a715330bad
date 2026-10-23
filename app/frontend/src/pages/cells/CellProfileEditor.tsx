import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useBlocker, useNavigate, useParams } from "react-router";
import { api, unwrap, type Schemas } from "../../backend/client";
import { Badge } from "../../components/Badge";
import { Banner } from "../../components/Banner";
import { Button, LinkButton } from "../../components/Button";
import { Card } from "../../components/Card";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { NumberInput, TextInput } from "../../components/Field";
import { Icon } from "../../components/Icon";
import { Select } from "../../components/Select";
import { ErrorState, Skeleton } from "../../components/States";
import { CAVEATS } from "../../caveats";
import { count, dateTime } from "../../format";
import { PlaceholderMark } from "./PlaceholderMark";
import { LABELS, placeholders, saveError, type Group, type ProfileKey } from "./profileFields";
import { VersionHistory } from "./VersionHistory";
import styles from "./Cells.module.css";

type Saved = Schemas["CellProfileResponse"];
type Profile = Schemas["CellProfile"];
type Mount = Schemas["FingerMount"];
type Hole = Schemas["MountHole"];
type Locating = Schemas["LocatingFeature"];
type Camera = Schemas["Camera"];
type Sim = Schemas["CellSimSettings"];

/** Saving failed: the API's message, and the editor group it's about when that can be told. */
class SaveFailed extends Error {
  constructor(
    message: string,
    readonly group?: Group,
  ) {
    super(message);
  }
}

/** #/cells/:id: one cell profile version, edited as a whole and saved as the profile's next version. The id is
 *  a version's, so after a save the page moves to the new version's address. Fields still in `to_confirm` are marked
 *  as placeholders until someone marks them measured. */
export function CellProfileEditor() {
  const profileId = Number(useParams().id);
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  // A saved version never changes, so it's fetched once: a refetch must never reset the user's edits.
  const saved = useQuery({
    queryKey: ["cell-profiles", profileId],
    // openapi-fetch types responses with tuples widened to arrays; the data is the schema's, so it's typed as that
    queryFn: async () =>
      (await unwrap(api.GET("/api/cell-profiles/{profile_id}", { params: { path: { profile_id: profileId } } }))) as Saved,
    staleTime: Infinity,
    enabled: Number.isInteger(profileId),
  });
  const versions = useQuery({
    queryKey: ["cell-profiles", profileId, "versions"],
    queryFn: async () =>
      (await unwrap(api.GET("/api/cell-profiles/{profile_id}/versions", { params: { path: { profile_id: profileId } } }))) as Saved[],
    enabled: Number.isInteger(profileId),
  });

  const [draft, setDraft] = useState<Profile | null>(null);
  const savedId = saved.data?.id;
  useEffect(() => {
    if (saved.data) setDraft(structuredClone(saved.data.profile));
  }, [savedId]); // only when another version loads, never on a refetch of this one

  const leaving = useRef(false); // set just before moving to the saved version, so the unsaved-changes guard lets it go
  const save = useMutation({
    mutationFn: async (profile: Profile) => {
      const { data, error } = await api.PUT("/api/cell-profiles/{profile_id}", {
        params: { path: { profile_id: profileId } },
        body: { profile },
      });
      if (error !== undefined || !data) {
        const { message, group } = saveError((error as { detail?: unknown } | undefined)?.detail);
        throw new SaveFailed(message, group);
      }
      return data;
    },
    onSuccess: (next) => {
      void queryClient.invalidateQueries({ queryKey: ["cell-profiles"] });
      leaving.current = true;
      navigate(`/cells/${next.id}`, { replace: true });
    },
  });
  useEffect(() => {
    leaving.current = false;
    save.reset();
  }, [profileId]); // a new version starts clean

  const dirty = Boolean(saved.data && draft && JSON.stringify(draft) !== JSON.stringify(saved.data.profile));
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) => dirty && !leaving.current && currentLocation.pathname !== nextLocation.pathname,
  );

  if (saved.isPending || (saved.data && !draft)) return <Skeleton height={480} />;
  if (saved.isError || !draft) {
    return (
      <ErrorState
        title="Couldn't load this cell"
        message={saved.error?.message ?? "Unknown cell."}
        onRetry={() => saved.refetch()}
      />
    );
  }

  const latest = versions.data?.at(-1);
  const toConfirm = placeholders(draft);
  const groupError = (group: Group) =>
    save.error instanceof SaveFailed && save.error.group === group ? <Banner tone="bad">{save.error.message}</Banner> : null;
  const set = <K extends ProfileKey>(key: K, value: Profile[K]) => setDraft((d) => d && { ...d, [key]: value });
  const setMount = (patch: Partial<Mount>) => set("finger_mount", { ...draft.finger_mount, ...patch });
  const setSim = (patch: Partial<Sim>) => set("sim", { ...draft.sim, ...patch });
  const mark = (key: ProfileKey) =>
    toConfirm.has(key) ? (
      <PlaceholderMark onMeasured={() => setDraft((d) => d && { ...d, to_confirm: d.to_confirm.filter((k) => k !== key) })} />
    ) : undefined;
  const mount = draft.finger_mount;
  const tongue = mount.face === "+x";

  return (
    <div className={styles.section}>
      <div className={styles.editorHead}>
        <div>
          <Link to="/cells" className={styles.note}>
            All cells
          </Link>
          <h2 className={styles.editorTitle}>{saved.data.name}</h2>
          <p className={styles.subtle}>
            Version {saved.data.version}, saved {dateTime(saved.data.created)}
          </p>
        </div>
        <div className={styles.badges}>
          {toConfirm.size > 0 && (
            <Badge tone="warn" label={count(toConfirm.size, "placeholder field", "placeholder fields")} title={CAVEATS.placeholderCell} />
          )}
        </div>
      </div>

      {latest && latest.id !== saved.data.id && (
        <Banner
          tone="info"
          title={`You're looking at version ${saved.data.version} of ${latest.version}.`}
          action={
            <LinkButton size="sm" to={`/cells/${latest.id}`}>
              Open version {latest.version}
            </LinkButton>
          }
        >
          Saving makes version {latest.version + 1} from these settings.
        </Banner>
      )}
      {saved.data.twin_mismatches.length > 0 && (
        <Banner tone="warn" title="Results simulate the twin's gripper.">
          {CAVEATS.twinMismatch} {saved.data.twin_mismatches.join("; ")}.
        </Banner>
      )}

      <div className={styles.layout}>
        <div className={styles.groups}>
          <Card title="Robot">
            {groupError("robot")}
            <div className={styles.fields}>
              <TextInput label={LABELS.robot_model} value={draft.robot_model} onChange={(v) => set("robot_model", v)} aside={mark("robot_model")} />
              <NumberInput
                label={LABELS.tcp_offset_mm}
                unit="mm"
                value={shown(draft.tcp_offset_mm)}
                onChange={(v) => set("tcp_offset_mm", required(v))}
                hint="J6 to the fingertips"
                aside={mark("tcp_offset_mm")}
              />
              <Select
                label={LABELS.approach}
                value={draft.approach}
                onChange={() => undefined}
                options={[{ value: "top-down", label: "Top-down" }]}
                hint="The only approach the sim models"
              />
              <NumberInput
                label={LABELS.lift_m}
                unit="m"
                step={0.01}
                value={shown(draft.lift_m)}
                onChange={(v) => set("lift_m", required(v))}
                hint="How far the part is lifted after the grasp"
                aside={mark("lift_m")}
              />
            </div>
          </Card>

          <Card title="Gripper">
            {groupError("gripper")}
            <div className={styles.fields}>
              <TextInput label={LABELS.gripper_model} value={draft.gripper_model} onChange={(v) => set("gripper_model", v)} aside={mark("gripper_model")} />
              <NumberInput
                label={LABELS.stroke_per_jaw_mm}
                unit="mm"
                value={shown(draft.stroke_per_jaw_mm)}
                onChange={(v) => set("stroke_per_jaw_mm", required(v))}
                hint="Each jaw's travel, closed to open"
                aside={mark("stroke_per_jaw_mm")}
              />
              <NumberInput
                label={LABELS.grip_force_n}
                unit="N"
                value={draft.grip_force_n}
                onChange={(v) => set("grip_force_n", v)}
                hint="At the cell's air pressure. Empty: the twin's jaw drive."
                aside={mark("grip_force_n")}
              />
              <NumberInput
                label={LABELS.air_pressure_mpa}
                unit="MPa"
                step={0.05}
                value={draft.air_pressure_mpa}
                onChange={(v) => set("air_pressure_mpa", v)}
                hint="Empty: not known"
                aside={mark("air_pressure_mpa")}
              />
              <div className={styles.wide}>
                <TextInput label={LABELS.stock_fingers} value={draft.stock_fingers} onChange={(v) => set("stock_fingers", v)} aside={mark("stock_fingers")} />
              </div>
              {(["Stock finger width", "Stock finger thickness", "Stock finger length"] as const).map((label, i) => (
                <NumberInput
                  key={label}
                  label={label}
                  unit="mm"
                  value={shown(draft.stock_finger_mm[i])}
                  onChange={(v) => set("stock_finger_mm", setAt(draft.stock_finger_mm, i, v))}
                  aside={i === 0 ? mark("stock_finger_mm") : undefined}
                />
              ))}
              <NumberInput
                label={LABELS.stock_tip_gap_mm}
                unit="mm"
                value={shown(draft.stock_tip_gap_mm)}
                onChange={(v) => set("stock_tip_gap_mm", required(v))}
                hint="Between the hooked tips, jaws fully open"
                aside={mark("stock_tip_gap_mm")}
              />
              <NumberInput
                label={LABELS.max_finger_length_mm}
                unit="mm"
                value={draft.max_finger_length_mm}
                onChange={(v) => set("max_finger_length_mm", v)}
                hint="The gripper maker's limit at the cell's air pressure. Empty: unknown."
                aside={mark("max_finger_length_mm")}
              />
              <NumberInput
                label="Free space along the jaw travel"
                unit="mm"
                value={shown(draft.free_space_mm[0])}
                onChange={(v) => set("free_space_mm", setAt(draft.free_space_mm, 0, v))}
                hint="How far a finger may reach from the centre, jaws open"
                aside={mark("free_space_mm")}
              />
              <NumberInput
                label="Free space across the jaws"
                unit="mm"
                value={shown(draft.free_space_mm[1])}
                onChange={(v) => set("free_space_mm", setAt(draft.free_space_mm, 1, v))}
                hint="How far a finger may reach to either side"
              />
              <NumberInput
                label={LABELS.mount_kept_mm}
                unit="mm"
                value={shown(draft.mount_kept_mm)}
                onChange={(v) => set("mount_kept_mm", required(v))}
                hint="The top of the blade kept as stock, where it's screwed to the jaw"
                aside={mark("mount_kept_mm")}
              />
            </div>
          </Card>

          <Card title="Finger mount" subtitle={tongue ? "Screws through the jaw into the blade's root" : "Screws through the blade's thickness"} aside={mark("finger_mount")}>
            {groupError("mount")}
            <div className={styles.fields}>
              <Select
                label={LABELS.face}
                value={mount.face}
                onChange={(event) => setMount({ face: event.target.value as Mount["face"] })}
                options={[
                  { value: "+x", label: "Tongue beside the root (+x, SMC jaw)" },
                  { value: "+y", label: "Flat against the jaw (+y face)" },
                  { value: "-y", label: "Flat against the jaw (-y face)" },
                ]}
                hint="The blade face that sits against the jaw"
              />
              {tongue && (
                <>
                  <NumberInput
                    label={LABELS.face_x_mm}
                    unit="mm"
                    value={shown(mount.face_x_mm)}
                    onChange={(v) => setMount({ face_x_mm: required(v) })}
                    hint="From the blade's inner face, jaws closed"
                  />
                  <NumberInput
                    label={LABELS.jaw_length_mm}
                    unit="mm"
                    value={shown(mount.jaw_length_mm)}
                    onChange={(v) => setMount({ jaw_length_mm: required(v) })}
                    hint="How far the jaw reaches down the blade"
                  />
                  <NumberInput
                    label={LABELS.jaw_clearance_mm}
                    unit="mm"
                    value={shown(mount.jaw_clearance_mm)}
                    onChange={(v) => setMount({ jaw_clearance_mm: required(v) })}
                  />
                </>
              )}
              <NumberInput
                label="Jaw face width"
                unit="mm"
                value={mount.face_size_mm ? shown(mount.face_size_mm[0]) : null}
                onChange={(v) => setMount({ face_size_mm: pairOrNull(mount.face_size_mm, 0, v) })}
                hint="Empty: not known"
              />
              <NumberInput
                label="Jaw face length"
                unit="mm"
                value={mount.face_size_mm ? shown(mount.face_size_mm[1]) : null}
                onChange={(v) => setMount({ face_size_mm: pairOrNull(mount.face_size_mm, 1, v) })}
              />
              <NumberInput
                label={LABELS.hole_clearance_mm}
                unit="mm"
                step={0.05}
                value={shown(draft.hole_clearance_mm)}
                onChange={(v) => set("hole_clearance_mm", required(v))}
                hint="Added to every printed hole, since printed holes come out undersized"
                aside={mark("hole_clearance_mm")}
              />
            </div>

            <Items
              title="Mount holes"
              items={mount.holes}
              noun="Mount hole"
              onAdd={() => setMount({ holes: [...mount.holes, newHole(tongue)] })}
              onRemove={(i) => setMount({ holes: mount.holes.filter((_, j) => j !== i) })}
              render={(hole, i) => {
                const setHole = (patch: Partial<Hole>) => setMount({ holes: mount.holes.map((h, j) => (j === i ? { ...h, ...patch } : h)) });
                return (
                  <>
                    <NumberInput label="Below the root" unit="mm" value={shown(hole.below_root_mm)} onChange={(v) => setHole({ below_root_mm: required(v) })} />
                    {tongue ? (
                      <NumberInput
                        label="Across the thickness"
                        unit="mm"
                        value={shown(hole.y_mm)}
                        onChange={(v) => setHole({ y_mm: required(v) })}
                        hint="From the blade's mid-plane"
                      />
                    ) : (
                      <NumberInput
                        label="Across the blade"
                        unit="mm"
                        value={shown(hole.x_mm)}
                        onChange={(v) => setHole({ x_mm: required(v) })}
                        hint="From its inner face"
                      />
                    )}
                    <NumberInput
                      label="Diameter"
                      unit="mm"
                      value={shown(hole.diameter_mm)}
                      onChange={(v) => setHole({ diameter_mm: required(v) })}
                      hint="Nominal; the clearance is added"
                    />
                    {tongue && (
                      <NumberInput
                        label="Depth"
                        unit="mm"
                        value={hole.depth_mm}
                        onChange={(v) => setHole({ depth_mm: v })}
                        hint="Empty: through the blade"
                      />
                    )}
                    <NumberInput
                      label="Counterbore diameter"
                      unit="mm"
                      value={hole.counterbore_diameter_mm}
                      onChange={(v) => setHole({ counterbore_diameter_mm: v })}
                      hint="Empty: no counterbore"
                    />
                    <NumberInput
                      label="Counterbore depth"
                      unit="mm"
                      value={shown(hole.counterbore_depth_mm)}
                      onChange={(v) => setHole({ counterbore_depth_mm: required(v) })}
                    />
                  </>
                );
              }}
            />

            {tongue && mount.locating.length === 0 ? (
              <p className={styles.note}>Locating pins and slots are only modelled on a +y or -y mount face.</p>
            ) : (
              <Items
                title="Locating features"
                items={mount.locating}
                noun="Locating feature"
                note={tongue ? "Remove these: locating pins and slots are only modelled on a +y or -y mount face." : undefined}
                onAdd={tongue ? undefined : () => setMount({ locating: [...mount.locating, newLocating()] })}
                onRemove={(i) => setMount({ locating: mount.locating.filter((_, j) => j !== i) })}
                render={(feature, i) => {
                  const setFeature = (patch: Partial<Locating>) =>
                    setMount({ locating: mount.locating.map((f, j) => (j === i ? { ...f, ...patch } : f)) });
                  return (
                    <>
                      <Select
                        label="Kind"
                        value={feature.kind}
                        onChange={(event) => setFeature({ kind: event.target.value as Locating["kind"] })}
                        options={[
                          { value: "pin", label: "Pin, standing out of the face" },
                          { value: "slot", label: "Slot, cut into the face" },
                        ]}
                      />
                      <NumberInput label="Below the root" unit="mm" value={shown(feature.below_root_mm)} onChange={(v) => setFeature({ below_root_mm: required(v) })} />
                      <NumberInput label="Across the blade" unit="mm" value={shown(feature.x_mm)} onChange={(v) => setFeature({ x_mm: required(v) })} />
                      <NumberInput
                        label={feature.kind === "slot" ? "Width" : "Diameter"}
                        unit="mm"
                        value={shown(feature.diameter_mm)}
                        onChange={(v) => setFeature({ diameter_mm: required(v) })}
                      />
                      {feature.kind === "slot" && (
                        <NumberInput label="Length" unit="mm" value={shown(feature.length_mm)} onChange={(v) => setFeature({ length_mm: required(v) })} />
                      )}
                      <NumberInput
                        label={feature.kind === "slot" ? "Depth" : "Height"}
                        unit="mm"
                        value={shown(feature.height_mm)}
                        onChange={(v) => setFeature({ height_mm: required(v) })}
                      />
                    </>
                  );
                }}
              />
            )}
          </Card>

          <Card title="Friction" subtitle={CAVEATS.estimatedFriction}>
            {groupError("friction")}
            <div className={styles.fields}>
              <TextInput label={LABELS.pad_material} value={draft.pad_material} onChange={(v) => set("pad_material", v)} aside={mark("pad_material")} />
              <NumberInput
                label="Pad friction, static"
                step={0.05}
                value={shown(draft.pad_friction[0])}
                onChange={(v) => set("pad_friction", setAt(draft.pad_friction, 0, v))}
                hint="Coefficient, printed pad on the part"
                aside={mark("pad_friction")}
              />
              <NumberInput
                label="Pad friction, sliding"
                step={0.05}
                value={shown(draft.pad_friction[1])}
                onChange={(v) => set("pad_friction", setAt(draft.pad_friction, 1, v))}
                hint="Coefficient"
              />
              <NumberInput
                label="Table mat friction, static"
                step={0.05}
                value={draft.mat_friction ? shown(draft.mat_friction[0]) : null}
                onChange={(v) => set("mat_friction", pairOrNull(draft.mat_friction, 0, v))}
                hint="Coefficient. Empty: not measured."
                aside={mark("mat_friction")}
              />
              <NumberInput
                label="Table mat friction, sliding"
                step={0.05}
                value={draft.mat_friction ? shown(draft.mat_friction[1]) : null}
                onChange={(v) => set("mat_friction", pairOrNull(draft.mat_friction, 1, v))}
                hint="Coefficient"
              />
            </div>
          </Card>

          <Card title="Cameras" aside={mark("cameras")}>
            {groupError("cameras")}
            <Items
              items={draft.cameras}
              noun="Camera"
              name={(camera) => camera.name || undefined}
              onAdd={() => set("cameras", [...draft.cameras, { name: "camera", width_px: 1920, height_px: 1080 }])}
              onRemove={(i) => set("cameras", draft.cameras.filter((_, j) => j !== i))}
              render={(camera, i) => {
                const setCamera = (patch: Partial<Camera>) => set("cameras", draft.cameras.map((c, j) => (j === i ? { ...c, ...patch } : c)));
                return (
                  <>
                    <TextInput label="Name" value={camera.name} onChange={(v) => setCamera({ name: v })} />
                    <NumberInput label="Width" unit="px" step={1} value={shown(camera.width_px)} onChange={(v) => setCamera({ width_px: required(v) })} />
                    <NumberInput label="Height" unit="px" step={1} value={shown(camera.height_px)} onChange={(v) => setCamera({ height_px: required(v) })} />
                  </>
                );
              }}
            />
          </Card>

          <AdvancedSim sim={draft.sim} onChange={setSim} error={groupError("sim")} forceOpen={Boolean(groupError("sim"))} />

          <div className={styles.saveBar}>
            <div className={styles.saveText}>
              <strong>{dirty ? "Unsaved changes" : "No changes"}</strong>
              <span>Saving makes a new version. Old versions never change, and every job records the version it used.</span>
              {save.error && !(save.error instanceof SaveFailed && save.error.group) && (
                <span className={styles.saveError}>{save.error.message}</span>
              )}
            </div>
            <div className={styles.actions}>
              <Button variant="secondary" disabled={!dirty || save.isPending} onClick={() => setDraft(structuredClone(saved.data.profile))}>
                Discard changes
              </Button>
              <Button disabled={!dirty || save.isPending} onClick={() => save.mutate(draft)}>
                {save.isPending ? "Saving" : `Save as version ${(latest?.version ?? saved.data.version) + 1}`}
              </Button>
            </div>
          </div>
        </div>

        <div className={styles.side}>
          <Card title="Placeholders">
            {toConfirm.size === 0 ? (
              <p className={styles.note}>Every field has been measured at the cell.</p>
            ) : (
              <>
                <p className={styles.note}>{CAVEATS.placeholderCell} Mark each one measured once it is.</p>
                <ul className={styles.list}>
                  {[...toConfirm].map((key) => (
                    <li key={key}>{LABELS[key] ?? key}</li>
                  ))}
                </ul>
              </>
            )}
          </Card>
          <Card title="Version history">
            {versions.isPending && <Skeleton height={120} />}
            {versions.isError && <p className={styles.saveError}>{versions.error.message}</p>}
            {versions.data && <VersionHistory versions={versions.data} viewing={saved.data.id} />}
          </Card>
        </div>
      </div>

      <ConfirmDialog
        open={blocker.state === "blocked"}
        title="Leave without saving?"
        confirmLabel="Leave and lose the changes"
        cancelLabel="Keep editing"
        danger
        onConfirm={() => blocker.proceed?.()}
        onClose={() => blocker.reset?.()}
      >
        Your edits to {saved.data.name} aren't saved. Leaving throws them away.
      </ConfirmDialog>
    </div>
  );
}

/** The sim settings, collapsed by default: the sim server runs with its own flags, so these rarely matter. */
function AdvancedSim({ sim, onChange, error, forceOpen }: { sim: Sim; onChange: (patch: Partial<Sim>) => void; error: ReactNode; forceOpen: boolean }) {
  const [open, setOpen] = useState(false);
  const shownOpen = open || forceOpen;
  return (
    <Card
      title="Advanced sim settings"
      aside={
        <Button variant="ghost" size="sm" onClick={() => setOpen(!shownOpen)} aria-expanded={shownOpen}>
          {shownOpen ? "Hide" : "Show"}
        </Button>
      }
    >
      {shownOpen && (
        <>
          {error}
          <div className={styles.fields}>
            <NumberInput
              label={LABELS.physics_dt_s}
              unit="s"
              step={0.001}
              value={shown(sim.physics_dt_s)}
              onChange={(v) => onChange({ physics_dt_s: required(v) })}
              hint="1/60 s by default"
            />
            <NumberInput
              label={LABELS.solver_position_iterations}
              step={1}
              value={shown(sim.solver_position_iterations)}
              onChange={(v) => onChange({ solver_position_iterations: required(v) })}
              hint="Iterations per physics step"
            />
            <NumberInput
              label={LABELS.solver_velocity_iterations}
              step={1}
              value={shown(sim.solver_velocity_iterations)}
              onChange={(v) => onChange({ solver_velocity_iterations: required(v) })}
              hint="Iterations per physics step"
            />
            <NumberInput
              label={LABELS.contact_offset_mm}
              unit="mm"
              step={0.05}
              value={shown(sim.contact_offset_mm)}
              onChange={(v) => onChange({ contact_offset_mm: required(v) })}
            />
            <NumberInput
              label={LABELS.rest_offset_mm}
              unit="mm"
              step={0.05}
              value={shown(sim.rest_offset_mm)}
              onChange={(v) => onChange({ rest_offset_mm: required(v) })}
            />
            <div className={styles.wide}>
              <NumberInput
                label={LABELS.envs}
                step={1}
                value={shown(sim.envs)}
                onChange={(v) => onChange({ envs: required(v) })}
                hint="64 environments is about 8 designs per round"
              />
            </div>
          </div>
        </>
      )}
    </Card>
  );
}

type ItemsProps<T> = {
  title?: string;
  items: T[];
  noun: string; // each item's heading, numbered: "Mount hole 1"
  name?: (item: T) => string | undefined; // a name to add to the heading, e.g. a camera's
  note?: string;
  onAdd?: () => void;
  onRemove: (index: number) => void;
  render: (item: T, index: number) => ReactNode; // the item's fields
};

/** An editable list of small records (mount holes, locating features, cameras): each a box of fields with Remove, and
 *  Add at the end. */
function Items<T>({ title, items, noun, name, note, onAdd, onRemove, render }: ItemsProps<T>) {
  return (
    <div className={styles.section}>
      {title && <h3 className={styles.itemHead}>{title}</h3>}
      {note && <Banner tone="warn">{note}</Banner>}
      {items.length === 0 && <p className={styles.note}>None.</p>}
      {items.map((item, i) => (
        <div key={i} className={styles.item}>
          <div className={styles.itemHead}>
            <span>
              {noun} {i + 1}
              {name?.(item) ? `: ${name(item)}` : ""}
            </span>
            <Button variant="ghost" size="sm" onClick={() => onRemove(i)}>
              Remove
            </Button>
          </div>
          <div className={styles.fields}>{render(item, i)}</div>
        </div>
      ))}
      {onAdd && (
        <div>
          <Button variant="secondary" size="sm" onClick={onAdd}>
            <Icon name="plus" />
            Add {noun.toLowerCase()}
          </Button>
        </div>
      )}
    </div>
  );
}

// A required number left empty is kept as NaN, so the field shows empty and saving reports it from the API's checks.
function required(value: number | null): number {
  return value ?? Number.NaN;
}

function shown(value: number): number | null {
  return Number.isNaN(value) ? null : value;
}

function setAt<T extends number[]>(tuple: T, index: number, value: number | null): T {
  const next = [...tuple] as T;
  next[index] = required(value);
  return next;
}

/** An optional pair (the jaw face's size, the mat's friction): null once both halves are empty. */
function pairOrNull(pair: [number, number] | null | undefined, index: number, value: number | null): [number, number] | null {
  const next = setAt<[number, number]>(pair ?? [Number.NaN, Number.NaN], index, value);
  return next.every(Number.isNaN) ? null : next;
}

function newHole(tongue: boolean): Hole {
  return tongue
    ? { below_root_mm: 4, x_mm: 6, y_mm: 0, diameter_mm: 2.5, depth_mm: 6, counterbore_diameter_mm: null, counterbore_depth_mm: 1 }
    : { below_root_mm: 10, x_mm: 6, y_mm: 0, diameter_mm: 3.2, depth_mm: null, counterbore_diameter_mm: 5.2, counterbore_depth_mm: 1 };
}

function newLocating(): Locating {
  return { kind: "pin", below_root_mm: 6, x_mm: 6, diameter_mm: 2, length_mm: 0, height_mm: 1 };
}
