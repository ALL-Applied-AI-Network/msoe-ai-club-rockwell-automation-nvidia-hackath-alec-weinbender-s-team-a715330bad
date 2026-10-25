# Auto-Grasp User Stories

Oct 25, 2026 · @Matt Weinbender

## Overview

Auto-Grasp has 17 user stories across two users. They follow a new part from upload to a qualified finger on the cell. Each story names the user, what they need, and the inputs they give and outputs they get. Nothing here specifies how the backend works.

| User | Role in Auto-Grasp |
| --- | --- |
| Manufacturing engineer | Primary user. Brings in new parts, runs evaluations, decides whether a new finger is worth making. |
| Robotics engineer | Sets up the cell hardware, finger library and grasp policy; validates fingers on the real robot. |

The manufacturing engineer always makes the final call on creating a new finger. The app shows success rates and failure reasons but sets no fixed pass bar, since even optimized fingers may not reach one for every part.

## Part intake

| # | Story | Inputs | Outputs |
| --- | --- | --- | --- |
| 1 | **Manufacturing engineer:** I want to upload the CAD of an incoming part, so it can be evaluated before the part reaches the cell. | STEP or STL file; part name and number | Part record with a 3D preview and bounding dimensions |
| 2 | **Manufacturing engineer:** I want to enter the part's physical properties, so results reflect how the real part behaves in a grip. | Mass; material or surface finish; maximum allowed grip force; rigid or deformable | Saved properties; missing fields flagged, with the default the app will use shown |
| 3 | **Manufacturing engineer:** I want to describe how the part is presented to the robot, so evaluations match what the cell will actually see. | Presentation type (bin, tray, fixture, conveyor); expected orientations or pose range | Saved presentation scenario shown on the 3D preview |
| 4 | **Manufacturing engineer:** I want to mark surfaces the fingers must not touch and any required approach direction, so cosmetic or critical surfaces are protected. | Selected faces or regions on the 3D model; approach direction | Keep-out zones and approach limits highlighted on the preview and applied to every evaluation of that part |
| 5 | **Manufacturing engineer:** I want to upload a whole batch of parts at once, so I can assess a new customer order or product mix in one go. | Multiple CAD files plus a CSV of part numbers and properties | Part list with intake status per part (ready, missing data, file error) |

## Hardware and finger library

| # | Story | Inputs | Outputs |
| --- | --- | --- | --- |
| 6 | **Robotics engineer:** I want to set up a profile for each gripper and cell, so every evaluation uses the right hardware limits. | Gripper model (or stroke, max force, finger mounting interface); robot arm; cell name | Saved gripper and cell profile, selectable in evaluations |
| 7 | **Robotics engineer:** I want to register the fingers we already own, so they can be evaluated against new parts. | Finger CAD; compatible gripper; finger family (e.g., V-pad, flat pad); material; quantity on hand | Library entry with a 3D preview, linked to its gripper profile |
| 8 | **Manufacturing engineer:** I want to browse and filter the finger library, so I can see what we have and where each finger has worked before. | Filters: family, gripper, parts evaluated, success rate | Finger list with each finger's evaluated parts and best success rates |

## Evaluation

| # | Story | Inputs | Outputs |
| --- | --- | --- | --- |
| 9 | **Robotics engineer:** I want to choose which grasp policy an evaluation uses, so the success rates match how our robots will actually grasp. | Policy from a list (e.g., our VLM+IK pipeline); policy version | Policy and version attached to the evaluation and shown on every result |
| 10 | **Manufacturing engineer:** I want to evaluate a new part against every compatible finger in the library, so I know whether we can run it with what we have. | Part (or batch); finger set (all compatible, or a filtered subset); policy; number of trials | Running job with progress and estimated time to finish; a notification when it's done |
| 11 | **Manufacturing engineer:** I want to re-run past parts when the library or policy changes, so old results don't go stale. | Part set; reason (new finger added, policy updated) | Updated success rates with changes from the previous run highlighted |

## Results and decisions

| # | Story | Inputs | Outputs |
| --- | --- | --- | --- |
| 12 | **Manufacturing engineer:** I want to see each finger's success rate on a part with how many trials it's based on, so I can decide whether an existing finger is good enough. | Completed evaluation | Fingers ranked by success rate, each with trial count and a confidence range; an option to start finger generation from that part |
| 13 | **Manufacturing engineer:** I want to see why grasps failed and watch replays of failed trials, so I can judge whether a finger is close or hopeless. | A finger-and-part result | Failure breakdown (slip, drop, collision, unreachable pose, keep-out violation); replay of individual trials |

## Finger generation

| # | Story | Inputs | Outputs |
| --- | --- | --- | --- |
| 14 | **Manufacturing engineer:** I want to generate a new finger for a part where our existing fingers aren't good enough, starting from a finger family we trust, so I get a usable design without drawing one by hand. | Part; starting family (e.g., V-pad); gripper profile; policy; optional target success rate; size and fabrication limits (max length, print material) | A few ranked candidate designs, each with a 3D preview, predicted success rate and failure breakdown |
| 15 | **Manufacturing engineer:** I want to generate one finger that covers several parts, so we make fewer fingers and swap less often. | Set of parts; minimum acceptable rate per part; optional priority per part | Shared finger design with predicted success rate per part, compared with what single-part fingers would achieve |
| 16 | **Robotics engineer:** I want to export an approved design and add it to the library, so it can be printed and used on future parts. | Chosen candidate; export format | STEP or STL file with mounting interface; new library entry marked simulated, not yet validated on the robot |

## Real-robot validation

| # | Story | Inputs | Outputs |
| --- | --- | --- | --- |
| 17 | **Robotics engineer:** I want to log real-robot test results for a finger on a part, so the library shows real performance next to the simulated prediction. | Finger; part; number of real trials and successes; notes | Real success rate shown beside the simulated rate; finger marked validated; gap between the two flagged when large |

## Feature summary

The stories imply 13 features. The suggested first build covers the demo path: upload a part, evaluate it against the library, see the result, and generate a finger when it falls short.

| Feature | Stories | Suggested phase |
| --- | --- | --- |
| Part upload and properties | 1, 2 | First build |
| Gripper and cell profiles | 6 | First build |
| Finger library (register, browse) | 7, 8 | First build |
| Policy selection | 9 | First build |
| Evaluation runner with progress | 10 | First build |
| Results view with confidence and a generate option | 12 | First build |
| Single-part finger generation | 14 | First build |
| Design export and add to library | 16 | First build |
| Presentation scenarios and keep-out zones | 3, 4 | Later |
| Batch upload and re-evaluation | 5, 11 | Later |
| Failure breakdown and trial replay | 13 | Later |
| Multi-part finger generation | 15 | Later |
| Real-robot validation log | 17 | Later |

No user sees usage metrics yet, but the app should log time from part upload to a qualified finger and the share of parts that ran on existing fingers. The pitch's closing line needs those numbers.
