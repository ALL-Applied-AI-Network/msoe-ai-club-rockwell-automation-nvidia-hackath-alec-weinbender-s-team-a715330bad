# Auto-Grasp

**Can we grip this new part reliably, and if not, what finger should we use?** Alec Weinbender's Team, Rockwell
Automation + NVIDIA Innovation Lab, Fall 2026, Dataset 3: Grasping and Sorting.

Auto-Grasp answers that question for a factory before a new part reaches the robot cell. It takes the part's CAD (or a
batch of parts), the factory's existing finger library, the gripper model and how accurately the cell grasps (how far a
grasp may land from where it was aimed), and works in the FANUC ER-4iA digital twin in Isaac Sim:

1. **Evaluate the finger library.** Every finger already on the shelf is simulated against the new part, at the part's
   candidate grasps and across the cell's grasp error, giving a ranked success rate per finger. The factory learns
   whether it can run the part with what it has, without trial and error at the cell, and which fingers cover many
   parts (fewer finger swaps).
2. **The factory decides.** It sees the best success rate its current fingers can reach, with the failure reasons, and
   decides whether that's good enough. The app sets no fixed pass bar.
3. **Generate a finger.** If not, Bayesian optimization tunes a trusted finger family (for example a V-pad's angle, depth
   and pad width) for one part or across several at once. The output is a printable finger with its predicted success
   rate, in place of days of manual design and test-and-revise cycles.
4. **The library grows.** Each new finger joins the library, so future parts are more likely to be covered by existing
   fingers. Real-robot results are logged next to the sim's prediction.

It's built for two users: the **manufacturing engineer**, who brings in new parts, runs evaluations and makes the call
on a new finger, and the **robotics engineer**, who sets up the gripper and cell, the finger library and the cell's
grasp accuracy, and validates fingers on the real robot.

Auto-Grasp evaluates **fingers, not a grasp policy**. Its results hold for any pipeline that locates the part and then
grasps it (vision plus IK, a VLM plus IK), at the stated accuracy. Learned closed-loop policies, which keep reacting
during the grasp, would have to be evaluated by running them. The full use case is in
**[docs/application-broad-overview.md](docs/application-broad-overview.md)** and the 17 user stories, with the
suggested first build, in **[docs/Auto-Grasp User Stories.md](<docs/Auto-Grasp User Stories.md>)**.

**What's built today.** The app runs two kinds of **job** on the sim:
- **Generation jobs** (step 3, one part at a time): batch BO over a V-pad finger family, scored by expected success
  under the cell's grasp error, against the stock fingers and a shape-fit (imprint) design. They come with CAD export
  and a tracker for printed fingers and real-arm trials.
- **Evaluation jobs** (step 1): every finger in the **finger library** is tried on a part at its candidate grasps and
  ranked.

Around them: a parts library with bulk upload, cell profiles that carry their grasp accuracy, and real-robot results
logged per finger and part. The evaluation side is backend only so far: its screens and multi-part generation aren't
built, and it has run on the mock sim, not yet in Isaac.

The project started as *CAD-to-Fingers* (our [team plan](docs/02-team-plan.md)); the name and use case changed on
2026-10-25.

Project state, hardware facts and open questions: **[CONTEXT.md](CONTEXT.md)**. Read
**[docs/notes/things-to-know.md](docs/notes/things-to-know.md)** before you start. All source documents: **[docs/](docs/README.md)**.

## Repository layout

```text
app/        Auto-Grasp web app: FastAPI backend + single-file frontend      → app/README.md
sim/        FANUC ER-4iA Isaac Sim twin (organizer starter v0.5) + sim service    → sim/README.md
docs/       Use case + user stories, event docs, team plan, references, experiments → docs/README.md
cad/        The organizers' CAD of the cell (gripper, screw, bin, cubes, vial)   → cad/README.md
cell_policy/ Our policy + submission for the organizers' real-robot platform     → cell_policy/README.md
data/       Local datasets (gitignored)                                          → data/README.md
SETUP.md    First-time setup: Git, uv, Python, VS Code, then each component
AGENTS.md   Instructions for coding agents (CLAUDE.md and GEMINI.md import it)
CONTEXT.md  Living project summary
```

## Quick start

**First time here? Follow [SETUP.md](SETUP.md)**: installing Git, uv and Python, cloning, and the one-time setup
(including the pre-commit guard).

Once you're set up, run the web app with the mock LLM and mock simulator, from the repo root:

```bash
uv sync --all-packages                                        # one .venv at the root for every component
uv run --package backend uvicorn api.main:app --port 8000       # open http://localhost:8000
```

Optional real backends are set in `.env`; see [.env.example](.env.example) and [app/README.md](app/README.md).
The digital twin needs Isaac Sim on a GPU machine (Brev or the MSOE GB10); see [sim/README.md](sim/README.md).

## Event links

- **Event guide** (datasets, compute, rules, judging): <https://msoe-maic.com/library/?article=Rockwell-NVIDIA-Fall-2026>
- **Team workspace** (team, repo access, submissions): <https://dashboard.all-ai-network.org/j/L36HEH>
- **Submissions** (team plan, final): <https://dashboard.all-ai-network.org/s/V28NHK>
- **Slack:** [join](https://join.slack.com/t/rockwellnvidi-wq82211/shared_invite/zt-4bp05nsn9-UW3afFtM9wjzWtZiQoJBHg).
  Our channel is `#dataset-3-grasping-sorting`; testbed requests go to `#data-and-testbed-requests`.

| When | What |
| --- | --- |
| Wed Oct 14, 11:59 PM CT | Team plan: submitted |
| **Sun Nov 1, 11:59 PM CT** | **Final submission:** ~5 min video, one-page summary, this repo, references |
| Thu Nov 5, 5:00–8:00 PM | Finals at MSOE Diercks Hall |

## Safety

Nothing in this repo commands the physical robot. Physical tests happen only at CSI, under supervision, after review. No
printed finger is mounted before it has been reviewed for clearance and safe operation. See
[docs/references/collect-and-test-your-own-data.md](docs/references/collect-and-test-your-own-data.md).

## Credits

- FANUC ER-4iA digital twin starter v0.5: provided by the hackathon organizers (UWM CSI / MSOE AI Club); see
  [sim/fanuc_er4ia_sim/](sim/fanuc_er4ia_sim/).
- NVIDIA Isaac Sim, Cosmos3-Nano; FANUC robot USD from the Isaac Sim asset library.
- *(Add data, models, code and tools used as the project grows; this list is part of the final submission.)*
