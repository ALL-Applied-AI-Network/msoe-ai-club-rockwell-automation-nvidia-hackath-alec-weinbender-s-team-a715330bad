# cad/

The organizers' CAD models of the real cell, **unchanged**, as downloaded from the hackathon dashboard's CAD Models page
(<https://hackathon.sidclab.org/#resources/cad-models>, files under `https://hackathon.sidclab.org/files/`) with `curl` on
2026-10-20. The page itself is stored in [docs/07-cad-models.md](../docs/07-cad-models.md). `SHA256SUMS` holds each
file's hash as downloaded. Check it with `sha256sum -c SHA256SUMS` from this folder. The page says more parts will
follow: add them here with their hashes, and say where they came from.

Don't edit these files. Anything derived from them (a tessellation, a twin asset, a texture crop) goes next to the code
that uses it, with a note naming the source file.

| File | What | Units, origin |
| --- | --- | --- |
| `SMC-MHZL2-16D2.step` | The gripper on the wrist: SMC's model, body and both jaws (open) | mm. Jaws travel along y, fingers point +z, the body's front face is at z = 7.5 |
| `ISO10642-M6x30-countersunk-screw.step`, `.stl` | M6 × 30 countersunk screw (threads not modelled) | mm. Head top face at z = 0, tip at z = −30 |
| `manipbench-bin-50x50x55.step`, `.stl` | The bin: 50 × 50 × 55 mm, pocket 35 × 35 × 25 mm | mm |
| `manipbench-cube-10mm.step`, `.stl` | 10 mm cube | mm. Origin at the bottom face's centre |
| `manipbench-cube-16mm.step`, `.stl` | 16 mm cube, 1 mm edge radius | mm. Origin at the bottom face's centre |
| `csi-vial.usda`, `csi-vial.stl` | Clear plastic vial, Ø27.18 × 203 mm (part 0890-01) | USD in inches, STL in mm. Origin at the bottom centre |
| `csi-vial-cap.usda`, `csi-vial-cap.stl` | Yellow tapered cap, Ø31.75 mm flange, 15.7 mm tall | USD in inches, STL in mm |
| `manipbench-table-surface.png` | The real work surface from above, 3128 × 2260 px | For the sim's tabletop |

## What we know about them

- `SMC-MHZL2-16D2.step` has the same SHA-256 as the twin's gripper source (`sim/fanuc_er4ia_sim/assets/gripper/
  smc_mhzl2_16d2.json`, `"sha256"`). `csi-vial.usda` and `csi-vial-cap.usda` are byte-identical to the twin's
  `assets/usd_assets/vial.usda` and `vial_cap.usda`.
- **Each jaw, from the STEP (measured with CadQuery, 2026-10-20).** In the jaw's own terms:
  - It is a base block that stands 2.3 mm out of the body's front face. Its inner faces are 0.15 mm from the centreline
    with the jaws closed.
  - A flat **tongue** stands out of that base: 5 mm thick along the jaw travel, 8 mm wide and 15 mm long.
  - The tongue's inner face is 7.45 mm from the gripper's centreline with the jaws closed (13.45 mm open).
  - Two **Ø3.4 mm** holes (M3 clearance) go through the tongue **along the jaw travel**, on its centreline, **4.0 and
    11.0 mm below the shoulder** (7 mm apart).

  This is the default finger mount in the app's cell profile (`app/backend/src/api/models/cell_profile.py`,
  `SMC_FLAT_JAW_MOUNT`). Confirm it on the real jaw before printing.
- Every STEP and STL here imports through the app's part upload (`CadQueryCad.read_part`), so the screw, the cubes and the
  vial can be used as parts directly.
