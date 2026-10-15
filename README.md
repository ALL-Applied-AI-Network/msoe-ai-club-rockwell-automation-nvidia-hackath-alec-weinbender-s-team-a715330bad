# CAD-to-Fingers

**Automated, simulation-validated gripper finger design for new parts.** Alec Weinbender's Team, Rockwell Automation + NVIDIA
Innovation Lab, Fall 2026, Dataset 3: Grasping and Sorting.

Give it a new part and a task, and it proposes finger templates with an LLM, then optimizes their dimensions with Bayesian
optimization. Each candidate is tested with repeated, deliberately mis-localized grasps in the FANUC ER-4iA digital twin.
The output is printable finger CAD, a grasp pose and a predicted success rate, which we then check against the stock fingers
on the real arm.

Project state, hardware facts and open questions: **[CONTEXT.md](CONTEXT.md)**. Read
**[docs/notes/things-to-know.md](docs/notes/things-to-know.md)** before you start. All source documents: **[docs/](docs/README.md)**.

## Repository layout

```text
app/        Finger Designer web app: FastAPI backend + single-file frontend      → app/README.md
sim/        FANUC ER-4iA Isaac Sim twin (organizer starter v0.5) + sim service    → sim/README.md
docs/       Event docs, team plan + feedback, references, experiment log         → docs/README.md
data/       Local datasets (gitignored)                                          → data/README.md
fanuc_er4ia_hackathon_starter_v05.zip   Untouched copy of the organizer twin download (unpacked in sim/)
AGENTS.md   Instructions for coding agents (CLAUDE.md and GEMINI.md import it)
CONTEXT.md  Living project summary
```

## Quick start

Run the web app locally with the mock LLM and mock simulator:

```bash
cd app
python -m venv .venv && . .venv/Scripts/activate      # Windows Git Bash; use .venv/bin/activate on Linux/macOS
pip install -r requirements.txt
python -m uvicorn backend.main:app --port 8000        # open http://localhost:8000
```

Optional real backends are set with environment variables; see [.env.example](.env.example) and [app/README.md](app/README.md).
The digital twin needs Isaac Sim on a GPU machine (Brev or the MSOE GB10); see [sim/README.md](sim/README.md).

## Team setup (once per clone)

```bash
git config core.hooksPath .githooks   # enables the pre-commit guard (blocks >5 MB files, .env, checkpoints)
```

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
