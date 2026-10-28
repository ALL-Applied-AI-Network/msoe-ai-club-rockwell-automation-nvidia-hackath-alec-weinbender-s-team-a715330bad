# Docs

Every document for the project lives here: event pages, our proposal, organizer feedback, reference pages and our own
notes. Source documents are stored **as received** (cleaned of web navigation, text otherwise unchanged). Our own
commentary is kept separate, in clearly labelled "Our notes" blocks or in [../CONTEXT.md](../CONTEXT.md).

To add a new document, use the `add-doc` skill (Claude Code) or follow [Conventions](#conventions) by hand.

## Index

### Core documents (numbered in the order received)

| # | Document | Kind | Received |
| --- | --- | --- | --- |
| 00 | [Original repo README](00-original-repo-readme.md): organizer template (links, dates, checklist) | event | 2026-10-15 |
| 01 | [Hackathon overview](01-hackathon-overview.md): schedule, judging, deliverables, contacts | event | 2026-10-15 |
| 02 | [Team plan + organizer feedback](02-team-plan.md): our CAD-to-Fingers proposal (the project's name until 2026-10-25) | proposal | 2026-10-15 |
| 03 | [Dataset 3: Grasping and Sorting](03-dataset-3-grasping-sorting.md): our challenge | dataset | 2026-10-15 |
| 04 | [MSOE GB10 access](04-gb10-access.md): `spark1.ai.msoe.edu` over the VPN, shared (password redacted) | event | 2026-10-20 |
| 05 | [Brev credits](05-brev-credits.md): $500 for the team, on Alec's account | event | 2026-10-20 |
| 06 | [Participant dashboard](06-participant-dashboard.md): the real-robot platform (policy client, submission, slots, scoring, FAQ), hackathon.sidclab.org | event | 2026-10-20 |
| 07 | [CAD Models](07-cad-models.md): the cell's gripper, screw, bin, cubes, vial, cap and table texture (files in [../cad/](../cad/README.md)) | dataset | 2026-10-20 |

### References (pages linked from the core documents)

| Document | Linked from | Status |
| --- | --- | --- |
| [Collect and Test Your Own Data](references/collect-and-test-your-own-data.md) | 01, 03 | complete |
| [Tools and Resources](references/tools-and-resources.md): task/tool/hardware table, Isaac Sim on Brev tutorial | 01, 00 | complete (link URLs not included) |
| [FANUC ROS 2 Driver Quick Start](references/fanuc-ros2-driver-quickstart.md) | 03 | complete |
| [Isaac Sim Manipulator Robot Assets](references/isaac-sim-manipulator-assets.md) | 03 | index page only |
| [Isaac Sim ROS 2 Joint Control](references/isaac-sim-ros2-joint-control.md) | 03 | **partial (truncated)** |
| [Client package](references/physicalai-client-package.md): README, submission templates, frames (SIDCLab/PhysicalAI-Hackathon-2026 at ff7534e) | 06 | complete (code not vendored) |
| [AI Plays Robotics](references/ai-plays-robotics.md): the organizers' essay on the screw-picking task | 06 | complete (videos not stored) |

### Not yet received

Linked from the documents above but not provided yet:

- Compute: Brev, DGX Spark, and build.nvidia.com (01)
- Coding agents (01)
- Isaac Lab and Isaac Sim on DGX Spark (03). Until it arrives, the GB10 steps follow NVIDIA's
  [Spark playbook](https://build.nvidia.com/spark/isaac/isaac-sim) ([GPU test plan, 0.2](notes/gpu-test-plan.md#02-msoe-gb10-free-shared-set-up))
- Brev Getting Started Doc (05)
- FANUC Tech Transfer video library (03, Tools and resources)
- Rest of the Isaac Sim ROS 2 Joint Control page (03)
- The stock finger CAD (03) and the further parts the CAD Models page says will follow (07)

### Our working docs

| Location | What |
| --- | --- |
| [application-broad-overview.md](application-broad-overview.md) | **The use case:** what Auto-Grasp does for a factory, step by step (evaluate the finger library, decide, generate, the library grows) |
| [Auto-Grasp User Stories.md](<Auto-Grasp User Stories.md>) | **The 17 user stories** (manufacturing engineer, robotics engineer), their inputs and outputs, and the features with a suggested first build |
| [../CONTEXT.md](../CONTEXT.md) | Current project state: facts, constraints, decisions, open questions |
| [notes/things-to-know.md](notes/things-to-know.md) | Gotchas, mismatches and warnings everyone should read |
| [notes/bo-assessment.md](notes/bo-assessment.md) | Local launch commands, GB10 access handoff and a proposed equal-budget BO/Sobol benchmark |
| [notes/benchmark-runbook.md](notes/benchmark-runbook.md) | Portable BO/Sobol/genetic runner, mock checks, CPU-physics GB10 handoff and result return instructions |
| [notes/gpu-test-plan.md](notes/gpu-test-plan.md) | Runbook: bring up the sim server on Brev / the GB10 and validate it step by step |
| [notes/cadquery-design.md](notes/cadquery-design.md) | CadQuery as the CAD kernel: why fingers are built as convex solids, the finger mount, part import, V-HACD, what's left to do |
| [notes/input-flow-backend-plan.md](notes/input-flow-backend-plan.md) | The input-flow and outputs backend plan: decisions D1–D17, models, pipeline, sim contract v2, workstreams |
| [notes/library-evaluation-backend-plan.md](notes/library-evaluation-backend-plan.md) | The plan for the user stories' first build: finger library, evaluation jobs, grasp accuracy on the cell, bulk part upload, qualifications per finger and part (decisions L1–L16, workstreams W1–W9) |
| [notes/backend-api.md](notes/backend-api.md) | The backend API as built, screen by screen, for the frontend; demo data (`DEMO_DATA=true`) |
| [notes/frontend-plan.md](notes/frontend-plan.md) | The frontend plan: every screen and user flow, GPU choice and help, caveats, priorities, backend gaps |
| [notes/submission-summary.md](notes/submission-summary.md) | DRAFT one-page summary for the final submission: problem, business case, method, results (placeholders), limitations |
| [experiments/](experiments/) | Simulation and physical trial log (required for measured results) |
| [images/](images/) | Images referenced by the docs |
| [../cad/](../cad/README.md) | The organizers' CAD of the cell, unchanged, with hashes and what we measured in it |
| [../cell_policy/](../cell_policy/README.md) | Our policy and submission for the real-robot platform (06) |
| [../sim/fanuc_er4ia_sim/docs/](../sim/fanuc_er4ia_sim/docs/) | Upstream twin docs: calibration v0.5, model notes |

## Conventions

- **File names:** core documents get the next number: `NN-short-kebab-title.md`. Pages that a core document links to go in
  `references/short-kebab-title.md`. Our own write-ups (designs, test plans, summaries) go in `notes/`.
- **Front matter:** every file starts with YAML front matter: `title`, `source` (URL or where it came from), `author`,
  `received` (YYYY-MM-DD), `kind` (`event | proposal | dataset | reference | feedback | note`), and optionally
  `linked_from` and `status`.
- **Fidelity:** keep the source wording. Strip site navigation, footers and "Is this page helpful?" chrome. Replace
  embedded images or videos you don't have with an italic placeholder.
- **Truncation:** if a paste is cut off, mark it `status: PARTIAL` and list it under *Not yet received*.
- **Images:** save to `images/` with a descriptive kebab-case name; reference them with relative links.
- **Follow-through:** when a document changes facts, decisions or deadlines, update [../CONTEXT.md](../CONTEXT.md) too,
  and add a row to the index above.
