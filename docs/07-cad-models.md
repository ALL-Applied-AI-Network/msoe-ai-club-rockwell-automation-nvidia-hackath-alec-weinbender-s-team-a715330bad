---
title: CAD Models
source: https://hackathon.sidclab.org/#resources/cad-models (files under https://hackathon.sidclab.org/files/)
author: SIDC Lab, UW-Milwaukee (platform developer), for UW-Milwaukee CSI and MSOE
received: 2026-10-20
kind: dataset
linked_from: 06-participant-dashboard.md (Resources)
---

# CAD Models

> **Our notes (not part of the source):**
>
> - **Where this came from:** the team shared this page's link in a Claude Code session on 2026-10-20 as the hackathon's
>   CAD-model page. Claude downloaded the page (part of the dashboard, [06](06-participant-dashboard.md)) and every
>   file it links to with `curl` that day. The files are in the repo, unchanged, in [../cad/](../cad/README.md), with
>   their SHA-256 hashes.
> - **The SMC STEP is the file the twin's gripper was built from** (same SHA-256 as
>   `sim/fanuc_er4ia_sim/assets/gripper/smc_mhzl2_16d2.json`'s source). The vial and cap USDs are byte-identical to the
>   twin's `assets/usd_assets/`. The screws, bin, both cubes as CAD, and the table texture are new to us.
> - **The jaw in the STEP doesn't match our old finger mount.** Each jaw ends in a flat tongue 5 mm thick along the
>   travel, 8 mm wide and 15 mm long. It has two Ø3.4 mm holes (M3 clearance) **along the jaw travel**, 7 mm apart, 4
>   and 11 mm below the shoulder it stands out of. The app's mount came from the twin's photo reconstruction: holes
>   through the blade's thickness, across the travel, 10 and 23 mm below the root. The 23 mm hole lies past the end of
>   the tongue. The app now builds the STEP's mount by default ([../CONTEXT.md](../CONTEXT.md), decisions). It is still
>   to be confirmed on the real jaw.
> - Measured with the app's own part import (`CadQueryCad.read_part`, 2026-10-20). All the files import:
>
>   | Part | Size (mm) | Notes |
>   | --- | --- | --- |
>   | M6 × 30 screw | head Ø12.0 × 3.3, shank Ø6.0, 30 long | 952 mm³ (about 7.5 g in steel); lies on its side 95% of the time |
>   | Bin | 50 × 50 × 55, pocket 35 × 35 × 25 | 108 cm³ solid |
>   | Cubes | 10 and 16 | the stock fingers' 12 mm straight-face opening can't take the 16 mm cube |
>   | Vial | Ø27.18 × 203 | hollow; too wide for the stock fingers; the twin scales it to Ø17 × 140 |
>   | Vial cap | flange Ø31.75, plug Ø20.8–23.6, 15.7 tall | |
>
> - The table texture is a photo of the real surface from above (3128 × 2260 px). The twin's `MAT_TEXTURE`
>   (`assets/mat_print.png`) isn't in the starter, so the twin renders a plain white table.

Models of the cell's hardware, for building your own simulation or planning around the real geometry. More parts will
follow.

## Gripper: SMC MHZL2-16D2

The parallel gripper on the robot's wrist: SMC's standard model of the gripper body, as published by SMC.

- Download STEP (243 KB): `files/SMC-MHZL2-16D2.step`
- 3D view on SMC:
  <https://www.smcetech.com/CC_host/pages/custom/modules/SolidWorks/viewWebGl3DCC.cfm?title=MHZL2%2D16D2&url=https://www.smcetech.com/modelCache/mhzl23171/MHZL2-16D2/3d/default/default/MHZL2-16D2.EASM>

## Object: M6 × 30 countersunk screw

The M6 screws on the cell: ISO 10642, 90° head, 4 mm hex socket. Threads are not modelled.

- STEP (34 KB): `files/ISO10642-M6x30-countersunk-screw.step`
- STL (96 KB): `files/ISO10642-M6x30-countersunk-screw.stl`

## Object: Bin, 50 × 50 × 55 mm

Every bin on the cell: 50 × 50 mm outside and 55 mm tall, with a 35 × 35 mm pocket 25 mm deep. The pocket's corner radius
is approximate.

- STEP (44 KB): `files/manipbench-bin-50x50x55.step`
- STL (27 KB): `files/manipbench-bin-50x50x55.stl`

## Object: Cubes, 10 mm and 16 mm

The cell's cubes, with rounded edges: 1 mm on the 16 mm cube; the 10 mm cube's is approximate. Origin at the bottom face's
centre.

- 10 mm: STEP `files/manipbench-cube-10mm.step`, STL `files/manipbench-cube-10mm.stl`
- 16 mm: STEP `files/manipbench-cube-16mm.step`, STL `files/manipbench-cube-16mm.stl`

## Object: Vial

Clear plastic vial, Ø27.18 × 203 mm, from its CAD (part 0890-01). USD in inches, as in the hackathon starter; STL in
millimetres.

Starter v0.5 scales the vial down to Ø17 × 140 mm. To match the real one, set `VIAL_RADIUS = 0.02718 / 2` and
`VIAL_LENGTH = 0.203` in the starter's `scene_config.py`; the cap is already the right size.

- USD (46 KB): `files/csi-vial.usda`
- STL (19 KB): `files/csi-vial.stl`

## Object: Vial cap

Yellow tapered plug with a Ø31.75 mm flange, 15.7 mm tall, from its CAD (MOCAP TWF.820/.930). USD in inches; STL in
millimetres.

- USD (91 KB): `files/csi-vial-cap.usda`
- STL (38 KB): `files/csi-vial-cap.stl`

## Table surface: Work surface texture

The real work surface seen from above, for the tabletop in your simulation.

- Download PNG (3.2 MB): `files/manipbench-table-surface.png`
