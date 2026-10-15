---
title: Innovation Lab Tools and Resources
source: https://msoe-maic.com/library?article=Rockwell-NVIDIA-Fall-2026-Resources
author: MSOE AI Club
published: 2026-10
received: 2026-10-15
kind: reference
linked_from: 01-hackathon-overview.md ("Tools and resources")
---

# Innovation Lab Tools and Resources

> **Our notes (not part of the source):**
>
> - For us, the relevant rows are **synthetic data / sim from a digital twin** and **robot policy training**: Isaac Sim on a
>   Brev launchable (**RTX PRO 6000 preferred**, L40S fallback about $3/hr) or the MSOE GB10. Record GPU, runtime and credits
>   used for each run (organizers asked for this). Log them in [../experiments/](../experiments/README.md).
> - The tutorial's example prompt asks the twin to pick up **screws**. Our starter (v0.5, `sim/fanuc_er4ia_sim/`) **omits the
>   screw policies** and does the six-cube stacking task instead (see its `docs/CALIBRATION_V05.md`). Adapt the prompt.
> - Cosmos Reason 3 (Edge/Nano) is what the starter's perception uses (Cosmos3-Nano). build.nvidia.com has free API access.
> - The source page's hyperlinks were not included in the paste; link titles are kept as plain text.

*Authors: MSOE AI Club · Published: October 2026*

A physical AI task-and-tool table, an Isaac Sim on Brev tutorial, and a focused reference list for in-context learning, industrial inspection, digital twins, synthetic data, NuRec, agents, and FANUC robotics.

This is a reference list, not a required reading list. Begin with the dataset page, build a simple baseline, and open the resource that answers the next concrete question.

## Physical AI tasks and tools

Use this table to match the task your team is working on to the tools and hardware that fit it. Costs are approximate Brev rates; check the rate shown in the Brev console before starting. "DGX Spark / GB10" means a UWM DGX Spark or an MSOE Dell GB10 on Rosie (see the Compute guide).

| Task | Inputs and outputs | Tools | Hardware |
| --- | --- | --- | --- |
| Agent orchestration harness | | NemoClaw | Brev launchable (free)<br>DGX Spark / GB10 |
| In-context learning | Outputs: reasoning answers (AOI, defect, root-cause analysis, etc.) | Cosmos Reason 3 Edge (single image), Nano (multiple images) | build.nvidia.com Reasoner, free (API keys)<br>DGX Spark / GB10<br>Brev (Edge on T4, about $0.50/hr; Nano on L40S, about $2/hr) |
| Automated inspection models (image-based) | | TAO, DEFT AOI, VisualChangeNet, Cosmos 3 | Training: Brev (RTX PRO 6000 preferred; L40S fallback about $2/hr; not yet tested), DGX Spark / GB10<br>Inference: DGX Spark / GB10 |
| Synthetic data generation from a digital twin with Emulate3D | Outputs: images, videos, actions, labels, etc. | Isaac Sim / Omniverse / Emulate3D Connector | GPU workstation at CSI |
| **Synthetic data generation from a digital twin** | Outputs: images, videos, actions, labels, etc. | Isaac Sim / Omniverse | Brev launchable (select RTX PRO 6000 when available; L40S fallback about $3/hr; see the tutorial below)<br>DGX Spark / GB10 |
| Synthetic data generation: GenAI image-to-image (I2I) inference | Inputs: images<br>Outputs: images | ChatGPT, Gemini, etc. | Cloud subscription for frontier models<br>DGX Spark / GB10 with FLUX.2 |
| Synthetic data generation: GenAI T2I, I2V, T2V, I2T (not I2I) inference | Inputs: text, images<br>Outputs: videos, actions, labels, etc. | Cosmos Reason 3 Edge (single image), Nano (multiple images). Cosmos 3 does not do I2I. | DGX Spark / GB10<br>build.nvidia.com Generator, free (API keys)<br>build.nvidia.com Reasoner, free (API keys) |
| Synthetic data generation: GenAI T2I, I2V, T2V, I2T (not I2I) fine-tuning | Inputs: text, images<br>Outputs: videos, actions, labels, etc. | Cosmos Reason 3 Edge (single image), Nano (multiple images) | Training: DGX Spark / GB10 (Edge: SFT; Nano: LoRA only)<br>Brev (Edge on 1× H100, about $5/hr; Nano on 4× A100 80 GB, about $8/hr) |
| Synthetic data generation: GenAI V2I, V2V, V2T, V2A | Outputs: images, videos, actions, labels, etc. | Cosmos Reason 3 Edge (480p, 150 frames max), Nano (720p, 400 frames max) | Inference: DGX Spark / GB10; build.nvidia.com Generator, free (API keys); build.nvidia.com Reasoner, free (API keys); Brev launchable (C2.5T, about $17/hr)<br>Training: DGX Spark / GB10 (Edge: SFT; Nano: LoRA only); Brev (Edge on 1× H100, about $5/hr; Nano on 4× A100 80 GB, about $8/hr) |
| **Robot policy training** | | Isaac Sim, Isaac Lab | Brev launchable (select RTX PRO 6000 when available; L40S fallback about $3/hr; see the tutorial below)<br>DGX Spark / GB10 |
| Reconstruct 3D scenes from images and lidar | | NuRec, Omniverse | Brev (L40S, about $2/hr) |
| Time-series forecasting | | NVIDIA Kumo-TS | Brev<br>DGX Spark / GB10 |

Abbreviations: T2I is text-to-image, I2V image-to-video, T2V text-to-video, I2T image-to-text, V2I video-to-image, V2V video-to-video, V2T video-to-text, V2A video-to-action, SFT supervised fine-tuning, and LoRA low-rank adaptation.

On Brev, prefer an RTX PRO 6000 for training and Isaac Sim when one is available. It costs roughly twice as much per hour as an L40S, but training may finish much faster. Record the GPU, runtime, and credits used so organizers can compare total cost and performance. See the Compute guide for details.

## Tutorial: synthetic data generation with Isaac Sim on Brev

This tutorial covers Isaac Sim on Brev without Cosmos 3. The launchable runs headless, which means there is no GUI. You interact with Isaac Sim from the command line, and any visual output is saved as images or videos that you copy to your computer to view. Coding agents work well in this environment, so plan to use one on the instance.

1. Start the Isaac Sim launchable.
   - This may take up to 10 minutes.
   - The launch screen may not update, so click **Compute** to check whether it is running.
2. Under Compute, you should see your running environment. *(Image: Brev Compute page showing a running Isaac Sim launchable on an L40S.)*
3. Click the environment box to open more information on how to copy files and access the instance.
   - CLI access to the instance is recommended.
   - Log in, then open a local terminal or a code editor.
   - Copy files from a separate terminal; that is usually easiest.
4. Install your preferred coding agent from the command line. For example, Claude Code:

   ```bash
   curl -fsSL https://claude.ai/install.sh | bash
   echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
   source ~/.bashrc
   ```

5. Do the work you planned.
6. To share the instance, follow the instructions under **Secure Links**.
7. **Stop your instance when you are done** so you do not use credits unnecessarily.
   - Select **Stop**. Stopping takes a few minutes.
   - Stopping freezes the instance and should keep your data, but save everything important elsewhere to avoid accidental loss.
   - Stopping does not stop storage costs. Storage is usually cheap (cents per hour), but delete any instance you are completely done with.
   - Deleting an instance removes all of its data, so only delete it when you are sure you do not need the data.
   - To resume a stopped instance, select **Start**. It should be ready within a few minutes, from the point where you stopped it. *(Image: a stopped Brev instance with Start and Delete buttons.)*

### Extra: robot arm digital twin

Download the FANUC digital twin. It is calibrated to the cameras on the grasping cell. Questions about the robot go to zhenzeng@uwm.edu.

1. Copy the FANUC digital twin zip to the Isaac Sim instance. Use your own file path and the instance name shown in Brev:

   ```bash
   brev copy /path/to/fanuc_er4ia_sim.zip <instance-name>:/home/ubuntu
   ```

2. Unzip the file on the instance:

   ```bash
   unzip fanuc_er4ia_sim.zip
   ```

3. Ask the agent to build the digital twin and render a video of it picking up screws. For example:

   > Set up the digital twin in Isaac Sim that is located in fanuc_er4ia_sim and generate a video of it picking up the screws from the table. Tell me where the video is located.

   This took Claude about five minutes to set up the twin and render the video.

4. Copy the video to your computer, watch it, and prompt the agent to update the twin:

   ```bash
   brev copy <instance-name>:/home/ubuntu/fanuc_er4ia_sim/demo.mp4 /path/to/Downloads
   ```

## AI coding tools

Agents can help inspect data, write a baseline, run experiments, and document a result. Review generated code, keep credentials outside the repository, and save enough information for another teammate to reproduce the run.

See the Coding agents guide to start free with Gemini in the Antigravity CLI, set up student access, and request Claude or Codex plans in your team plan.

## In-context learning

In-context learning gives a general vision-language model examples and instructions in the prompt instead of first training a dedicated model. For automated optical inspection, the context often contains examples of acceptable and defective parts.

It is useful for a fast baseline and rare classes. Large foundation models can be slower and more expensive than a small trained model, so they may not fit a high-throughput edge deployment.

- NVIDIA guide to vision-language prompt engineering
- Few-shot visual inspection paper
- Paper code
- Cosmos model matrix
- Cosmos 3 quickstart

## Industrial inspection

- Vision AI for industrial inspection overview
- TAO 7.0.1 getting started
- Visual ChangeNet documentation
- TAO DEFT AOI agent workflow
- TAO vision-language model fine-tuning

The DEFT AOI workflow is a useful structure even when a team uses different tools: evaluate, inspect failure cases, add or generate targeted examples, retrain, and gate the new version against a fixed test.

## Digital twins and synthetic data

- What is a digital twin?
- Rockwell and NVIDIA factory digital twins
- Assembling digital twins with Omniverse and OpenUSD
- Isaac Sim scene-based synthetic dataset generation
- Replicator and synthetic-data introduction
- Three workflows for improving vision AI with synthetic data
- Physical AI Data Factory augmentation pipeline

See the Isaac Sim on Brev tutorial above, and the Compute guide for Brev accounts and costs.

## Video and standard operating procedures

- SOP monitoring tutorial
- SOP Monitoring Blueprints
- SOP training workflow
- SOP inference workflow

These resources are most relevant when the project must understand a sequence rather than classify one frame.

## NuRec and real-to-sim

- NuRec for robotics
- Monocular neural reconstruction
- Neural volume rendering in Isaac Sim
- Large-scale 3D Gaussian splatting session

## Agents and factory data

- NeMoClaw
- NeMoClaw quickstart
- Create a workflow with NeMo Agent Toolkit
- Factory Operations FOX Blueprint
- FactoryTalk Optix OPC UA tutorial
- NVIDIA Kumo time-series models

The FOX material provides architecture context but not a complete implementation for this testbed. FactoryTalk or OPC UA access must be approved; teams should not connect to plant systems on their own.

## FANUC and robotics

- Official FANUC ROS 2 driver quickstart → [fanuc-ros2-driver-quickstart.md](fanuc-ros2-driver-quickstart.md)
- FANUC manipulator assets in Isaac Sim → [isaac-sim-manipulator-assets.md](isaac-sim-manipulator-assets.md)
- Isaac Sim ROS 2 manipulation tutorial → [isaac-sim-ros2-joint-control.md](isaac-sim-ros2-joint-control.md) (partial)
- FANUC Tech Transfer

## Before adding another tool

Write down:

- What failure in the current baseline the tool should address.
- What input and output it requires.
- What compute and access it needs.
- How the team will compare it with the baseline.

If those answers are unclear, keep the current pipeline simple and ask a mentor.
