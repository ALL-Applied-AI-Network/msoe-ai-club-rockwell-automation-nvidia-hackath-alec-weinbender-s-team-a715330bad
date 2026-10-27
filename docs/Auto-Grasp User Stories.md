# Auto-Grasp User Stories

Oct 25, 2026 · @Alec Weinbender

## Overview

Auto-Grasp has 17 user stories across two users. They follow a new part from upload to a qualified finger on the cell. Each story names the user, what they need, and the inputs they give and outputs they get. Nothing here specifies how the backend works.

| User | Role in Auto-Grasp |
| --- | --- |
| Manufacturing engineer | Primary user. Brings in new parts, runs evaluations, decides whether a new finger is worth making. |
| Robotics engineer | Sets up the cell hardware, finger library and the cell's grasp accuracy; validates fingers on the real robot. |

The manufacturing engineer always makes the final call on creating a new finger. The app shows success rates and failure reasons but sets no fixed pass bar, since even optimized fingers may not reach one for every part.

## Part intake

| # | Story | Inputs | Outputs |
| --- | --- | --- | --- |
| 1 | **Manufacturing engineer:** I want to upload the CAD of an incoming part, so it can be evaluated before the part reaches the cell. | STEP or STL file; part name and number | Part record with a 3D preview and bounding dimensions |
| 2 | **Manufacturing engineer:** I want to enter the part's physical properties, so results reflect how the real part behaves in a grip. | Mass; material or surface finish; maximum allowed grip force; rigid or deformable | Saved properties; missing fields flagged, with the default the app will use shown |
| 3 | **Manufacturing engineer:** I want to choose which ways the part can lie when it reaches the robot, so evaluations match what the cell will actually see. For now, parts are presented on a flat table. | Which of the part's stable resting poses the cell will see (the likely ones are pre-selected, with how often each occurs) | Chosen poses shown on the 3D preview and covered by every evaluation of that part |
| 4 | **Manufacturing engineer:** I want to limit how the part may be gripped, so fingers only close where the cell can or should grip it. For now, every grasp is top-down. | Optional: a locked grasp direction, faces picked on the 3D model to grip, or a locked grip height | The allowed grasps highlighted on the preview; evaluations only try grasps within those limits |
| 5 | **Manufacturing engineer:** I want to upload many parts at once, so I can assess a new customer order or product mix in one go. | Several STEP or STL files, or a folder of them | Each file added to the parts library, with an intake status per file (ready, needs properties, file error) |

## Hardware and finger library

| # | Story | Inputs | Outputs |
| --- | --- | --- | --- |
| 6 | **Robotics engineer:** I want to set up a profile for each gripper and cell, so every evaluation uses the right hardware limits. | Gripper model (or stroke, max force, finger mounting interface); robot arm; cell name | Saved gripper and cell profile, selectable in evaluations |
| 7 | **Robotics engineer:** I want to register the fingers we already own, so they can be evaluated against new parts. | Finger CAD; compatible gripper; finger family (e.g., V-pad, flat pad); material; quantity on hand | Library entry with a 3D preview, linked to its gripper profile |
| 8 | **Manufacturing engineer:** I want to browse and filter the finger library, so I can see what we have and where each finger has worked before. | Filters: family, gripper, parts evaluated, success rate | Finger list with each finger's evaluated parts and best success rates |

## Evaluation

| # | Story | Inputs | Outputs |
| --- | --- | --- | --- |
| 9 | **Robotics engineer:** I want to set how accurately our cell grasps, so the success rates match the position error our robots actually have. | Grasp accuracy per cell: a preset (well calibrated, typical, cheap camera) or values measured on the cell (spread in position and rotation, any consistent offset) | Accuracy saved on the cell profile as its default, copied into each evaluation and generation run (which can override it), and shown on every result, with success across a range of accuracies so sensitivity is visible |
| 10 | **Manufacturing engineer:** I want to evaluate a new part against every compatible finger in the library, so I know whether we can run it with what we have. | Part (or batch); finger set (all compatible, or a filtered subset); grasp accuracy profile | Running job with progress and estimated time to finish; each finger tried at the part's candidate grasps and scored at its best; a notification when it's done |
| 11 | **Skipped for now.** ~~**Manufacturing engineer:** I want to re-run past parts when the library or the cell's grasp accuracy changes, so old results don't go stale.~~ | ~~Part set; reason (new finger added, accuracy re-measured)~~ | ~~Updated success rates with changes from the previous run highlighted~~ |

## Results and decisions

| # | Story | Inputs | Outputs |
| --- | --- | --- | --- |
| 12 | **Manufacturing engineer:** I want to see each finger's success rate on a part with how many trials it's based on, so I can decide whether an existing finger is good enough. | Completed evaluation | Fingers ranked by success rate, each with the number of simulated grasps it's based on; an option to start finger generation from that part |
| 13 | **Manufacturing engineer:** I want to see why grasps failed and watch replays of failed trials, so I can judge whether a finger is close or hopeless. | A finger-and-part result | Failure breakdown (slip, drop, collision, unreachable pose, keep-out violation); replay of individual trials |

## Finger generation

| # | Story | Inputs | Outputs |
| --- | --- | --- | --- |
| 14 | **Manufacturing engineer:** I want to generate a new finger for a part where our existing fingers aren't good enough, starting from a finger family we trust, so I get a usable design without drawing one by hand. | Part; starting family (e.g., V-pad); gripper profile; grasp accuracy profile; size and fabrication limits (max length, print material) | A few ranked candidate designs, each with a 3D preview, predicted success rate and failure breakdown, next to the best existing fingers from the evaluation |
| 15 | **Manufacturing engineer:** I want to generate one finger that covers several parts, so we make fewer fingers and swap less often. | Set of parts; minimum acceptable rate per part; optional priority per part | Shared finger design with predicted success rate per part, compared with what single-part fingers would achieve |
| 16 | **Robotics engineer:** I want to export an approved design and add it to the library, so it can be printed and used on future parts. | Chosen candidate; export format | STEP or STL file with mounting interface; new library entry marked simulated, not yet validated on the robot |

## Real-robot validation

| # | Story | Inputs | Outputs |
| --- | --- | --- | --- |
| 17 | **Robotics engineer:** I want to log real-robot test results for a finger on a part, so the simulated success rate for that finger-and-part pair is checked against reality. | Finger; part; number of real trials and successes; notes | Real success rate shown beside the simulated rate for that pair; the pair marked validated; gap between the two flagged when large |

## Feature summary

The stories imply 13 features. The suggested first build covers the demo path: upload parts, evaluate them against the finger library, see the result, generate a finger when it falls short, and check the prediction on the real robot. The app has two libraries, each with its own tab: parts and fingers.

| Feature | Stories | Suggested phase |
| --- | --- | --- |
| Part upload and properties, one file or many | 1, 2, 5 | First build |
| Resting poses and grasp limits (flat table, top-down) | 3, 4 | Built; keep as is for now |
| Gripper and cell profiles | 6 | Built; more cells are low priority for the demo |
| Finger library (register, browse) | 7, 8 | First build |
| Grasp accuracy profiles | 9 | First build |
| Evaluation runner with progress | 10 | First build |
| Results view with a generate option | 12 | First build |
| Single-part finger generation | 14 | Built; link it to evaluation results |
| Design export and add to library | 16 | First build |
| Real-robot validation per finger and part | 17 | First build |
| Failure breakdown and trial replay | 13 | Second build |
| Multi-part finger generation | 15 | Later |
| Re-evaluation when the library or accuracy changes | 11 | Skipped |

Presentation types other than a flat table (bins, trays, fixtures, conveyors), approach directions other than top-down, and keep-out zones are out of scope for now.

No user sees usage metrics yet, but the app should log time from part upload to a qualified finger and the share of parts that ran on existing fingers. The pitch's closing line needs those numbers.
