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

A new part is coming to a robot cell. The question on the floor is simple: **can the fingers we already have grip it
reliably, and if not, which finger should we make?** Today that is answered by printing or machining fingers and trying
them on the robot, which takes days, ties up the cell, and tests each finger only at the few positions anyone thought
of. The real risk is somewhere else: no camera, calibration or robot puts a grasp exactly where it was aimed, and a
finger that works at the centre can drop the part a few millimetres off.

## The business case

Most new parts can run on fingers already on the shelf. Auto-Grasp **tries the library first** and **generates a new
finger only as the fallback**:

1. Every finger in the factory's library is simulated against the new part, at its candidate grasps, across the
   cell's grasp error, and ranked by predicted success.
2. The manufacturing engineer decides whether the best one is good enough. There is no fixed pass bar.
3. If none is, Bayesian optimisation designs a printable finger for the part. It goes through a review gate before it
   is printed, and then joins the library, so the next part is more likely to need nothing new.

For another manufacturer this means fewer custom fingers, less time on the cell before a new part runs, and a number
to decide with instead of a trial-and-error loop. Inputs are a STEP or STL file, the cell's gripper, and how
accurately the cell grasps.

## The method

- **Digital twin.** NVIDIA Isaac Sim with the organizers' FANUC ER-4iA cell and the SMC MHZL2-16D2 gripper (6 mm per
  jaw). Each grasp is a scripted top-down pick: approach, close, lift.
- **Error grid.** Each finger is tested at a fixed grid of position and yaw offsets around the aimed grasp, not at
  random draws. One run then scores any grasp-accuracy level by re-weighting, with no new simulation, which gives a
  success-vs-error curve per finger.
- **Batch BO.** The fallback searches one V-pad finger family (pad width, slack, tip height, lead-in) with BoTorch
  (qLogNEI), several designs per Isaac request. The stock fingers and an imprint of the part are simulated in the same
  requests as baselines. The winner is exported as STEP and STL with the gripper's mount holes and an engraved ID.
- **Validation.** Printed fingers are run on the real arm through the organizers' platform, at the same commanded
  offsets as the stock fingers, and measured success is compared with the prediction (95% Wilson interval).

## Results (M6 × 30 countersunk screw, dropped into a bin)

| | Stock fingers | Imprint | Generated (D1) |
| --- | --- | --- | --- |
| Predicted success at 3 mm, 8° (Isaac, GB10) | TBD | TBD | TBD |
| Capture radius (Isaac) | TBD | TBD | TBD |
| Measured on the real arm (n, 95% interval) | TBD | not run | TBD |

- Success vs grasp error, 0.5 to 6 mm: chart TBD. The custom finger starts to win at TBD mm.
- Library evaluation: TBD fingers ranked in TBD min. Generation: TBD min for TBD designs.

## Limitations

- **No height error.** The grid varies position and yaw only. The fingertips close 2.5 mm above the table, so height
  error is a likely real failure that the sim never tests.
- **Landing capture.** A finger that lands on the part can push it into the gap and still count as a hold. A real
  arm may knock the part away instead, so near a design's edge the sim can flatter it, the stock baseline included.
- **Weak grip in the twin.** The simulated jaws grip at about 2.5 N, far below the gripper's rated force. Heavy or
  slippery parts score as drops for every finger. The 7.5 g screw is well inside what the twin holds.
- **Unmeasured grasp accuracy.** The 3 mm, 8° default is a placeholder until it is measured on the cell. The curves
  show every level, but the headline number depends on it.
- The sim's predictions are unvalidated until the real-arm trials are logged.
