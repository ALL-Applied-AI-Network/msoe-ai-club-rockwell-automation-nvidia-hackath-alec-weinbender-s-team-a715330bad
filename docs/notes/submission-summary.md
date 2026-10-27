---
title: Auto-Grasp, one-page summary for the final submission
source: our own write-up for the final submission (due 2026-11-01)
author: Alec Weinbender's Team
received: 2026-10-26
kind: note
status: DRAFT; results are placeholders (TBD) until the Isaac runs and the real-arm session are logged in docs/experiments/
---

# Auto-Grasp: will our fingers grip the new part?

Rockwell Automation + NVIDIA Innovation Lab, Fall 2026, Dataset 3 (Grasping and Sorting). Alec Weinbender's Team.

## The problem

A new part is coming to a robot cell: **can the fingers we already have grip it reliably, and if not, which finger
should we make?** Today the answer comes from making fingers and trying them on the robot. That takes days, ties up the
cell, and only tests the positions someone thought of. But no camera or robot grasps exactly where it aims, and a finger
that works at the centre can drop the part a few millimetres off.

## The business case

Most new parts can run on fingers already on the shelf, so Auto-Grasp **tries the library first** and **generates a
finger only as the fallback**:

1. **Rank the library.** Every finger is simulated against the new part, at its candidate grasps and across the cell's
   grasp error, and ranked by predicted success.
2. **The engineer decides.** The manufacturing engineer judges whether the best is good enough. There's no fixed pass
   bar.
3. **Generate if needed.** If none is good enough, Bayesian optimisation designs a printable finger. It passes a review
   gate, then joins the library.

For a manufacturer that means fewer custom fingers, less cell time, and a number to decide with. The inputs are a STEP
or STL file, the gripper, and how accurately the cell grasps.

## The method

- **Digital twin:** NVIDIA Isaac Sim with the organizers' FANUC ER-4iA cell and SMC MHZL2-16D2 gripper, running a
  scripted top-down pick.
- **Error grid:** each finger is tried at a fixed grid of position and yaw offsets. One run re-scores at any grasp
  accuracy with no new simulation, which gives a success-vs-error curve.
- **Honest holds:** a grasp where a finger knocked the part before the jaws closed counts as a miss, even if the
  simulator held it.
- **Batch BO:** BoTorch searches a V-pad finger family, several designs per Isaac request, with the stock fingers and an
  imprint of the part as baselines. The winner is exported as STEP and STL with the mount holes and an engraved ID.
- **Validation:** printed and stock fingers run on the real arm at the same commanded offsets, and measured success is
  compared with the prediction (95% Wilson interval).

## Results (M6 × 30 countersunk screw, dropped into a bin)

| | Stock fingers | Imprint | Generated (D1) |
| --- | --- | --- | --- |
| Predicted success at 3 mm, 8° (Isaac) | TBD | TBD | TBD |
| Measured on the real arm (n, 95% interval) | TBD | not run | TBD |

- **Success vs grasp error, 0.5 to 6 mm:** chart TBD.
- **Timing:** TBD fingers ranked in TBD min; TBD designs generated in TBD min.
- **What the screw taught us:** its Ø6 shank sits in the stock fingers' sweet spot. The gripper's 6 mm stroke per jaw
  caps every finger's slack, and every good generated design hit that cap. So for this part, stock is close to the best
  this gripper can do, and Auto-Grasp says so before anyone prints a finger.
- **Where generation pays off: the cell's 16 mm cube** (Isaac, 3 mm / 8°). It's as wide as the stock tips open, so stock
  scores 0% and the best library finger 17.6%. A generated finger reaches **92.3%** and holds every grasp out to 4.5 mm,
  found in 33 minutes of simulation.

## Limitations

- **No height error:** the grid varies position and yaw only.
- **Contact noise:** the fingers brush a small lying part differently each run. Two runs of one finger on the screw
  agree on about 80% of offsets and move 1–2 points, so smaller gaps aren't real.
- **Unmeasured inputs:**
  - **Grasp accuracy:** 3 mm and 8° is a placeholder.
  - **Friction:** the twin's stock tips are 1.5, our printed-finger estimate is 0.4.
  - **Knocks:** whether a real arm survives the size of knock we count as a miss.
- **Weak simulated grip:** about 2.5 N per jaw, fine for the 7.5 g screw but not for heavy parts.
- **Unvalidated:** the predictions stand unconfirmed until the real-arm trials are logged.
