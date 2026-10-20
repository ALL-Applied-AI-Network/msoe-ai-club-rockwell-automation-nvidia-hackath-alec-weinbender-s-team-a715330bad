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
| 02 | [Team plan + organizer feedback](02-team-plan.md): our CAD-to-Fingers proposal | proposal | 2026-10-15 |
| 03 | [Dataset 3: Grasping and Sorting](03-dataset-3-grasping-sorting.md): our challenge | dataset | 2026-10-15 |
| 04 | [MSOE GB10 access](04-gb10-access.md): `spark1.ai.msoe.edu` over the VPN, shared (password redacted) | event | 2026-10-20 |
| 05 | [Brev credits](05-brev-credits.md): $500 for the team, on Alec's account | event | 2026-10-20 |

### References (pages linked from the core documents)

| Document | Linked from | Status |
| --- | --- | --- |
| [Collect and Test Your Own Data](references/collect-and-test-your-own-data.md) | 01, 03 | complete |
| [Tools and Resources](references/tools-and-resources.md): task/tool/hardware table, Isaac Sim on Brev tutorial | 01, 00 | complete (link URLs not included) |
| [FANUC ROS 2 Driver Quick Start](references/fanuc-ros2-driver-quickstart.md) | 03 | complete |
| [Isaac Sim Manipulator Robot Assets](references/isaac-sim-manipulator-assets.md) | 03 | index page only |
| [Isaac Sim ROS 2 Joint Control](references/isaac-sim-ros2-joint-control.md) | 03 | **partial (truncated)** |

### Not yet received

Linked from the documents above but not provided yet:

- Compute: Brev, DGX Spark, and build.nvidia.com (01)
- Coding agents (01)
- Isaac Lab and Isaac Sim on DGX Spark (03). Until it arrives, the GB10 steps follow NVIDIA's
  [Spark playbook](https://build.nvidia.com/spark/isaac/isaac-sim) ([GPU test plan, 0.2](notes/gpu-test-plan.md#02-msoe-gb10-free-check-it-first))
- Brev Getting Started Doc (05)
- FANUC Tech Transfer video library (03, Tools and resources)
- Rest of the Isaac Sim ROS 2 Joint Control page (03)

### Our working docs

| Location | What |
| --- | --- |
| [../CONTEXT.md](../CONTEXT.md) | Current project state: facts, constraints, decisions, open questions |
| [notes/things-to-know.md](notes/things-to-know.md) | Gotchas, mismatches and warnings everyone should read |
| [notes/gpu-test-plan.md](notes/gpu-test-plan.md) | Runbook: bring up the sim server on Brev / the GB10 and validate it step by step |
| [notes/cadquery-design.md](notes/cadquery-design.md) | CadQuery as the CAD kernel: why fingers are built as convex solids, part import, V-HACD, what's left to do |
| [notes/input-flow-backend-plan.md](notes/input-flow-backend-plan.md) | The input-flow and outputs backend plan: decisions D1–D17, models, pipeline, sim contract v2, workstreams |
| [notes/backend-api.md](notes/backend-api.md) | The backend API as built, screen by screen, for the frontend; demo data (`DEMO_DATA=true`) |
| [experiments/](experiments/) | Simulation and physical trial log (required for measured results) |
| [images/](images/) | Images referenced by the docs |
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
