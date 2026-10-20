---
title: "AI Plays Robotics: From Instructions to Physical Actions"
source: https://hackathon.sidclab.org/#resources/ai-plays-robotics
author: SIDC Lab, UW-Milwaukee (platform developer)
received: 2026-10-20
kind: reference
linked_from: 06-participant-dashboard.md (Resources)
---

# AI Plays Robotics

> **Our notes (not part of the source):**
>
> - **Where this came from:** captured with the rest of the participant dashboard ([06](../06-participant-dashboard.md))
>   on 2026-10-20, with `curl`. The two videos are on the site (`/files/blog_screws_table_v2.mp4` and
>   `/files/blog_screws_side.mp4`) and are not stored here.
> - The running example is our candidate demo task: picking screws scattered on the table. For the submission's
>   `model_type`, our scripted policy with designed fingers is closest to "TAMP + FMs" or "Hybrid".

From Instructions to Physical Actions

## 1. Easy to Say, Hard to Do

Consider a task for a robotic arm:
"Pick up the screws scattered across the table."

*(Videos: table camera and side camera views of the task, with playback speeds 1×, 2×, 4×, 8×.)*

For a human, the instruction requires little explanation. We look at the objects, decide how to pick them up, and adjust
our movements as we go.

For a robot, the details matter.

A screw's position and orientation may be different every time the robot looks at the table. Even identifying the right
object does not guarantee a successful grasp.

This task illustrates a broader problem in robotics. A robot needs to understand its surroundings, decide what to do, and
translate that decision into physical motion. In robotics, we often call these capabilities perception, planning, and
control.

The difficulty is that the physical world rarely behaves exactly as expected.

So how should we build a robot that can handle it?

## 2. What If We Let AI Decide?

One approach is to program the robot explicitly.

For a known object at a known position, a program might look like this:

```python
move_to(object_position)
close_gripper()
move_to(target_position)
open_gripper()
```

This works well when the environment is structured and the assumptions hold. Industrial robots have relied on this kind
of programming for decades, often with remarkable precision and reliability.

But our task introduces uncertainty. A screw may appear somewhere the program did not expect.

We could add cameras, detection algorithms, grasping rules, and recovery procedures. For sufficiently constrained tasks,
this can work very well. But each new variation may require another decision about how the robot should respond.

What if some of those decisions could instead be made by AI?

Recent advances in robot learning and foundation models [1, 2] offer several ways to approach this. A robot might learn
movements from demonstrations, use a vision-language model to reason about a scene, or predict the consequences of an
action before executing it.

Rather than prescribing every movement, we can give the system observations and let it determine what actions to take.

This raises another question: what should the AI actually look like?

## 3. One Robot, Many Ways to Think

There is no single architecture for turning AI decisions into robot actions.

Some systems learn to map camera images directly to movements. Others separate high-level reasoning from low-level
execution. Still others use explicit planners or predictive models of the physical world.

Here are several approaches worth exploring:

| Approach | |
| --- | --- |
| Visuomotor Policy | Learns actions from visual observations and demonstrations |
| VLA | Predicts robot actions from images and language instructions |
| VLM + BM | Uses a vision-language model to make decisions and a behavior model to execute them |
| TAMP + FMs | Combines foundation models with explicit task and motion planning |
| WAM | Uses predictions of future world states to guide actions |
| Your Architecture | Combines approaches or introduces something new |

Each approach offers a different way to tackle the same underlying problem.

For picking screws, a vision-language system might identify the objects and choose grasping strategies, while a motion
planner handles the robot's movements.

None of these choices guarantees success.

A model may correctly identify an object but fail to grasp it. A planner may produce a valid trajectory that does not
account for an object slipping. A learned policy may perform well on familiar arrangements but struggle when the scene
changes.

The interesting question is not just whether an AI can produce a plausible action.

Can it make that action work on a real robot?

## 4. Let's Find Out

We provide a shared industrial robotic testbed where you can define your own manipulation task, build your AI policy, and
test it on a real robot.

Through a common interface, your AI receives observations and returns robot actions. We handle physical execution and
evaluate whether your system completes the task.

What can your AI make a robot do?

## References

1. K. Black et al. π0: A Vision-Language-Action Flow Model for General Robot Control. arXiv:2410.24164, 2024.
   <https://arxiv.org/abs/2410.24164>
2. Gemini Robotics Team. Gemini Robotics: Bringing AI into the Physical World. arXiv:2503.20020, 2025.
   <https://arxiv.org/abs/2503.20020>
