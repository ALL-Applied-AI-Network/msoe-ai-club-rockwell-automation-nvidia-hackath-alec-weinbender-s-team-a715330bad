---
title: "Team plan: CAD-to-Fingers (submitted) + organizer feedback"
source: ALL AI Network event workspace, team plan checkpoint
author: Alec Weinbender's Team
submitted: 2026-10-14 19:48 CDT
received: 2026-10-15
kind: proposal
---

# Team plan: CAD-to-Fingers

**Team:** Alec Weinbender's Team
**Title:** CAD-to-Fingers: Automated, Simulation-Validated Gripper Finger Design for New Parts
**Checkpoint:** Team plan, due Oct 14, 11:59 PM CDT (submitted; last updated 10/14/2026, 7:48:50 PM CDT; editable until the checkpoint closes)

| Field | Value |
| --- | --- |
| Dataset | Dataset 3: Grasping and Sorting |
| Compute requested | Dell GB10 at MSOE (Rosie), Brev |
| Compute estimate and justification | All MSOE students. Can use ROSIE or Brev easily |
| Additional data needed and why | Finger, gripper, and mount CAD: the dataset page lists finger CAD; we also need the gripper body and mount interface so generated fingers bolt on correctly. |

## Problem

High-mix, low-volume lines often need new gripper fingers whenever a new part is introduced. Today, an engineer designs those fingers by hand and tunes them by trial and error on the robot. 3D printing has made fingers fast to make, but designing and validating them is still slow. Poorly matched fingers cause slips, drops, and re-picks, especially when the camera's estimate of where the part is isn't perfect.

## Our pipeline

We will build a tool that takes a new part and a task, and outputs ready-to-print fingers for the existing SCHUNK gripper, validated in simulation before anything touches the real robot.

1. **Input:** the new part's CAD file (or images) plus a short task description, e.g. "move tennis balls into a bowl" or "place eggs into a carton."
2. **Pick a starting design:** an LLM chooses a finger template (flat pads, V-groove, or a pocket shaped to the part) and sets initial dimensions.
3. **Optimize in simulation:** Bayesian optimization adjusts the finger dimensions (groove angle, pocket clearance, finger length, etc.). Each candidate is tested with repeated grasps in the FANUC ER-4iA digital twin, with the part placed slightly off from where the camera says it is. The design that succeeds most often wins, so the fingers tolerate realistic camera and calibration error.
4. **Output:** printable finger CAD, the matching grasp pose for the robot, and a predicted success rate.
5. **Validate:** print the top 2–3 designs and test them on the real arm against the stock fingers and a simple shape-fit ("imprint") design.

**Stretch goal:** train a model on the simulation results that predicts a design's success rate instantly. It would screen out bad candidates before simulating them, making each new part faster to onboard than the last.

## Business case

- **Faster changeovers:** a new part goes from CAD to validated fingers in hours instead of days to weeks of manual design and trial-and-error.
- **Scales across parts and plants:** works with the gripper a plant already owns. Fingers cost a few dollars to print, and no new robot or high-end camera is needed. Fingers that tolerate placement error also make a cheaper camera setup good enough.
- **Builds trust:** every design arrives with a predicted success rate and a simulation-tested safety check, so operators know what to expect before running it.
- **Can be sold as a service:** for example, a vendor like Rockwell offering it alongside its digital-twin tools, where customers upload a part and receive validated fingers.

---

## Organizer feedback (received after submission)

> Team-
>
> Thank you for submitting your team plan to the 2026 Physical AI for the Factory Floor Hackathon sponsored by Rockwell Automation and NVIDIA.
>
> Organizers reviewed your proposal and have some feedback for your team in these areas:
>
> **Problem/focus**
>
> The problem you proposed looks aligned with the hackathon goals, and you should be able to put together a great solution. We would suggest that you consider the specific items you want to pick and place as not all of the existing items will fit in the fingers. You can either target smaller items that fit in the jaws or explore redesigning the fingers to accommodate larger items. Grasping possibilities can be explored via the digital twin.
>
> Automating finger design is aligned with the hackathon. Please choose a specific manufacturing part and task for the first demonstration, confirm the actual mounting geometry, and compare generated fingers with the standard fingers. Treat a predicted simulation success rate as something to validate in physical trials.
>
> **Data needs**
>
> Feel free to review the provided assets. <https://msoe-maic.com/library?article=Rockwell-NVIDIA-Fall-2026-Grasping-Sorting>
>
> For additional recordings, measurements, or test sessions: Please post a request in #data-and-testbed-requests and tag Shamar Webster, or email webste63@uwm.edu. Include the test plan, requested duration, attendees, and dates. CSI must confirm the booking and supervision. Scheduling guidance: <https://msoe-maic.com/library?article=Rockwell-NVIDIA-Fall-2026-Data-Collection>
>
> **Compute requested**
>
> A separate message should be coming regarding brev credits.
>
> A separate message should be coming regarding access to an MSOE GB10 machine.
>
> When you have questions or need any clarification, please don't hesitate to reach out by responding to this email or sending a message on Slack at any point prior to 11/1.
>
> Good luck with your project!
> —Physical AI Hackathon Organizers

### Action items derived from the feedback

These are tracked in [../CONTEXT.md](../CONTEXT.md#open-questions--action-items):

1. Choose **one specific manufacturing part + task** for the first demo, sized to what the jaws can actually hold (or plan to redesign fingers for larger parts).
2. **Confirm the actual mounting geometry** (gripper body + finger mount interface). The twin models an SMC MHZL2-16D2, not a SCHUNK, so we need to confirm which one is on the real cell.
3. **Compare generated fingers against the standard fingers** (baseline).
4. Treat the simulated success rate as a **prediction to validate in physical trials** at CSI.
5. Watch for the separate Brev credits and GB10 access messages.
