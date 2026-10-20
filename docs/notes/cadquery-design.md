---
title: CadQuery integration (design notes and handover)
source: our own design note, written while moving the app's CAD to CadQuery
author: Alec Weinbender's Team
received: 2026-10-19
kind: note
status: DONE 2026-10-20; the "Not done yet" list was finished in the input-flow overhaul (see the note at the top)
---

# CadQuery integration: design notes and handover

> **Update 2026-10-20.** Everything under "Not done yet" was finished as part of the
> [input-flow overhaul](input-flow-backend-plan.md):
>
> - migration 0003 includes `cad_files`;
> - tests;
> - mesh parts in the sim contract.
>
> What's changed since this note:
>
> - The printable solid moved to `models/finger_cad.py`, and `finger.py` keeps the simulated solids (`finger_solids`).
> - Mount features, hole clearance and an engraved ID come from the cell profile.
> - Exports are a STEP of the pair plus one STL per side, with export checks.
> - Part import gained centre of mass, face types, a material hint and STL units.
> - A V-HACD call bug is fixed: faces were passed in the wrong layout, so pieces came out as slivers.
> - `/api/parts/measure` was replaced by stored parts (`POST /api/parts`).

## Status

Work in progress, **uncommitted**, on branch `batch-bo-sim-server` (the three commits before it are in). The finger
geometry and the CAD client are written, and their model tests pass (34/34). Everything listed under "Not done yet" still
needs doing. The backend suite is **not** green yet, because `scad_path` became `cad_files` without a migration.

## Goal

CadQuery (OpenCascade) is the single geometry kernel. The CAD solid is the ground truth, and what the simulator collides
with is derived from it. The CAD side covers:

- finger STEP and STL output, generated from the same solids as the simulation pieces;
- STEP and STL part input, measured and split into convex pieces;
- in principle anything else CAD-shaped.

## Coordinates (unchanged)

Everything is in the gripper frame G, in mm, with the jaws closed (jaw = 0):

- The origin is between the stock fingertips.
- +z points up toward the wrist; +x points along the jaw travel toward the finger being described; +y = z × x.
- The other finger is the mirror image in x.
- The stock blade occupies x 0..12, y −3..3, z 0..76. The sim server's tests check this against the twin's `cell.py`.
- Fingertips stay at z = 0, so the 293 mm TCP doesn't change.

## Decisions and why

**1. Fingers are built as convex solids in CadQuery, not decomposed afterwards.** Physics engines need convex pieces for
fast, reliable contact. We know the convex parts of our own design, so we build them directly:

- one extruded strip per straight segment of the pad's face profile, plus the bridge and the upper blade;
- the simulator gets exactly those solids, tessellated (`models/finger.py: build_finger → pieces`);
- the printable model is the same solids fused, with the mount holes cut (`finger_solid`).

Decomposing a finished mesh instead would be approximate, and it would blur exactly the features we optimize (a few-mm
V-groove, the imprint's 0.2 mm clearance). The verification is exact: the STEP solid's volume equals the pieces' volume
minus the mount holes' volume, 149.3 mm³, to the decimal. So the pieces don't overlap, and what we simulate is what we
print.

**2. Each piece goes through a hull.** `_piece` tessellates each convex solid. Every face is planar, so tessellation adds
no points. `hull_piece` (scipy) then produces outward-wound triangles. Every piece stays well under PhysX's 64-vertex hull
limit (at most about 10), and a test checks this.

**3. The lead-in chamfer is a cut by the plane x + z = face + lead.** Each strip has a triangular prism (a wedge)
subtracted, so every strip stays convex.

- The wedge is drawn on an explicit `cq.Plane` (local y = +z, normal −y) rather than the named "XZ" plane, whose
  orientation is easy to get wrong.
- The pad's thickness is depth + lead + 3 mm of wall. An earlier version let a deep lead-in eat the whole fingertip.
- A test checks that the bottom inner edge sits at face + lead with a full wall behind it. That test caught a 0.2 mm wedge
  error during the rewrite.

**4. The mount is in the STEP/STL only, not in the collision pieces.**

- It follows the twin's convention that cosmetic holes don't change contact. The cuts all lie in the top 30 mm of plain
  blade (`mount_kept_mm`), which is far above any part.
- **Default since 2026-10-20: SMC's jaw, from its STEP** (`cell_profile.SMC_FLAT_JAW_MOUNT`, face `+x`; `cad/README.md`).
  - Each jaw ends in a tongue 5 mm thick along the travel, 8 mm wide and 15 mm long. Its inner face is at x = 7.45 mm
    with the jaws closed.
  - The finger's root is cut back to x = 7.45 for 15.5 mm (the tongue plus 0.5 mm clearance), so the tongue seats
    against that face. Two Ø2.5 mm holes (plus the print clearance) go 6 mm into the root along -x, 4 and 11 mm below
    the root (z = 72 and 65), on the mid-plane, for M3 × 10 self-tapping screws through the tongue's Ø3.4 mm holes.
  - The blade's root is assumed to butt against the tongue's shoulder, so the fingertips stay where the stock ones are.
  - Checked against the STEP's jaw solid placed in G with the jaws closed: no overlap, faces touching, holes aligned.
- The twin's photo reconstruction is `PHOTO_MOUNT` (face `-y`): on the blade's centreline (x = 6), 10 and 23 mm below the
  root (z = 66 and 53), Ø3.2 mm through-holes along y with Ø5.2 × 1 mm counterbores on both faces. The STEP's jaw
  contradicts it: its holes run along the travel, and the 23 mm hole lies past the end of the tongue.
- `export_check.py` accounts for the step and holes along x in "matches sim", and checks the walls around them.
- Either way, confirm the mount on the real cell before anything is printed. That's an open item in CONTEXT.md.

**5. Output files.** `clients/cad.py: CadQueryCad.export(part, design, stem) → {"step": path, "stl": path}`.

- One compound holds both fingers, placed as mounted with the jaws open; the second is the first mirrored.
- STEP is the exact B-rep, for review and CAD tools; it re-imports as 2 solids. STL uses 0.01 mm chordal tolerance, for
  the slicer.
- Export takes about 0.4 s.
- OpenSCAD (`OpenScadCad`) is removed.

**6. Part input.** `CadQueryCad.read_part(filename, bytes) → PartCad` (`models/part_cad.py`).

- **STEP:** read with `cq.importers.importStep`, which gives exact solids; volume comes from the B-rep.
- **STL:** read with OCP's `RWStl.ReadFile_s`, because CadQuery 2.8 has no STL importer. Volume comes from signed
  tetrahedra.
- **Assumed orientation:** the file is taken as authored (mm, +z up, x along the jaws), then centred in x and y with its
  base at z = 0.
- **Shape fit**, used to prefill the existing cylinder/box `Part`:
  - a standing cylinder if the x–y footprint is round (extents agree within 3% and the hull fills the circle within 3%);
  - a lying cylinder if the x–z silhouette is round;
  - otherwise a box.
- **Mass** stays at its default, because density is unknown.
- **Checked on:** a cup-shaped vial cap (STEP and STL), a box, a 10 mm cube and a lying 17 × 140 mm tube. All matched
  correctly, each in under 1 s.

**7. V-HACD (`vhacdx`) for part decomposition, not CoACD.** Measured on the cup-shaped cap:

| | Time | Max vertices per piece |
|---|---|---|
| CoACD, defaults | 193 s | 104 |
| CoACD, tuned | 17 s | 64 |
| V-HACD | 1.3 s | 56 |

CoACD ignored the vertex cap unless decimation was on. V-HACD's coarser hulls are fine for parts.

- **Convex shortcut:** a part that's already convex, with at most 64 corners, becomes one exact piece. V-HACD returned a
  flat sliver hull for a plain box.
- **Degenerate hulls** are dropped; if none are left, the read fails with a clear error.

**8. Layering follows `.claude/rules/coding-style.md`.**

- Geometry computation is in `models/` (`finger.py`, `part_cad.py`).
- File I/O is in `clients/cad.py`.
- `services/parts.py` maps errors to `PartFileError`.
- `routers/parts.py` runs the CAD work in a thread pool, so the kernel doesn't block the event loop.
- The API lifespan now also creates the CAD client (for `/measure`), exposed through `CadDep` in `dependencies.py`.

**9. Interfaces were kept stable on purpose**, to avoid collisions with the frontend and simulation-pipeline work.
`Finger` (pieces, tip_height_mm, jaw_close_mm, contact_mm, friction) is unchanged, so the optimizer, the mock simulator
and the HTTP sim client don't change. The only optimizer edit is in `_finalize`: `cad.export(part, design, outputs_dir /
job_id)`, stored in `ResultRow.cad_files`.

**10. Performance.**

- `import cadquery` takes about 1.7 s warm (7.7 s cold) and loads VTK. It's imported normally.
- Building one design takes about 0.12 s, which adds roughly 16 s to a 128-design job.

**11. Dependencies.**

- Added to the backend only: `cadquery>=2.4` (resolved to 2.8.0, pulling in cadquery-ocp, vtk and trame) and
  `vhacdx>=0.1`. `coacd` was added during evaluation, then removed.
- The sim server doesn't need any of them, because it receives pieces.
- Unverified: cadquery-ocp wheels for linux-aarch64, which the MSOE GB10 uses. Run the backend on x86.

## API changes

- `GET /api/jobs/{id}/cad?format=step|stl`: the winning finger pair.
- `GET /api/jobs/{id}/scad`: a temporary redirect to `/cad?format=step`, kept only for the current UI link.
- `POST /api/parts/measure`: multipart with `part_file` (.step, .stp or .stl). It returns `PartCad` JSON (filename,
  source, extent_mm, volume_mm3, fit, suggested Part, pieces) and stores nothing.
- `JobResult.scad_path` is now `cad_files: dict[str, str]`, mapping format to path.

## Not done yet (in order)

1. **Migration 0003**, replacing `results.scad_path` with `cad_files` (JSON). Autogenerate it against a scratch DB at
   0002:

   ```bash
   DATA_DIR=<scratch> uv run --package backend alembic -c app/backend/alembic.ini upgrade 0002
   DATA_DIR=<scratch> uv run --package backend alembic -c app/backend/alembic.ini revision --autogenerate --rev-id 0003 -m "CAD files as STEP and STL"
   ```

   Old rows are demo data, so clearing `results` first (as 0002 did) is fine.
2. **Tests:**
   - `conftest.py`: replace `OpenScadCad` with `CadQueryCad`, and override `get_cad` in the `client` and
     `finished_client` fixtures.
   - `test_cad.py`: export writes both files, the STEP re-imports as 2 solids, `read_part` fits the cap, box and tube,
     and unknown or broken files are rejected.
   - `test_optimizer.py`: assert `cad_files` has step and stl, and the STEP starts with `ISO-10303-21`.
   - `routers/test_jobs.py`: test `/cad?format=step|stl` and the `/scad` redirect.
   - New tests for `part_cad` and for the parts service and router.
   - In `test_finger.py`: `finger_solid` volume equals the pieces' volume minus the mount holes'.
3. **Docs:** the CAD sections of `app/README.md`, `CONTEXT.md` (the CAD-output row and a decision row), and
   `docs/notes/things-to-know.md` (the "no mount holes" item).
4. **Frontend (other agent):**
   - Point the download at `/api/jobs/{id}/cad?format=step` and add an STL link. The "(.scad, no mount holes yet)" label
     is now wrong.
   - Optionally call `/api/parts/measure` on file upload, to prefill the part fields and preview `pieces`.
5. **Simulation pipeline (other agent): mesh parts.** The sim contract only knows cylinder and box parts. The natural
   extension:
   - Request: `part: {"shape": "mesh", "pieces": [{points, triangles}...], "mass_g"}`, in the same piece format as
     fingers, in the part's resting frame.
   - Sim server: author one rigid body with one `convexHull` collider per piece, as `clients/isaac.py` already does for
     finger pieces.
   - App mock: overlap tests would need polygon footprints for mesh parts.

## Files changed (uncommitted)

- **Backend dependencies:** `app/backend/pyproject.toml`, `uv.lock`.
- **Rewritten:** `models/finger.py` (construction on CadQuery, `finger_solid`, `hull_piece` made public, mount-hole
  constants), `clients/cad.py`.
- **New:** `models/part_cad.py`, `services/parts.py`, `routers/parts.py`.
- **Edited:**
  - `services/optimizer.py`: the `_finalize` export call; the unused `_describe` was removed.
  - `services/jobs.py`: `result_file(db, job_id, fmt)`.
  - `routers/jobs.py`, `dependencies.py`, `main.py`, `db/tables.py`, `models/job.py`.
