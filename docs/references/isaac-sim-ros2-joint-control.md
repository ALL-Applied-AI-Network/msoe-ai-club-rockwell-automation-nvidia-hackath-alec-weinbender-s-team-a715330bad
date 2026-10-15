---
title: "Isaac Sim — ROS 2 Joint Control: Extension Python Scripting"
source: Isaac Sim Documentation › Workflows › ROS 2 › Robot Control › ROS 2 Joint Control: Extension Python Scripting
author: NVIDIA
received: 2026-10-15
kind: reference
linked_from: 03-dataset-3-grasping-sorting.md ("Isaac Sim ROS 2 manipulation tutorial")
status: PARTIAL — the pasted text was cut off mid-code-block; ask for the rest
---

# ROS 2 Joint Control: Extension Python Scripting

> **Our notes (not part of the source):** this document is **incomplete**. The paste was truncated partway through the
> OmniGraph Python snippet below, so the rest of the snippet and any later sections are missing. The pattern itself
> (Action Graph: tick → read joint state → publish `/joint_states`; subscribe `/joint_command` → articulation controller)
> is how an external ROS 2 / MoveIt process would drive the ER-4iA twin. The starter itself does **not** use ROS 2; it
> drives the arm directly from Isaac Python (`sort_scene.py`, `ik.py`).

## Learning Objectives

In this tutorial, you interact with a manipulator, the Franka Emika Panda Robot. You:

- Add a ROS 2 Joint State publisher and subscriber in OmniGraph
- Add a ROS 2 Joint State publisher and subscriber using menu shortcut
- Add a ROS 2 Joint State publisher and subscriber using the OmniGraph Python API using the script editor

## Getting Started

**Prerequisite**

- Completed Development Methods to understand the Extension Workflow.
- Appropriate `ros2_ws` is sourced in the terminal that will be running Python scripts.
- `FASTRTPS_DEFAULT_PROFILES_FILE` environment variable is set prior to launching Isaac Sim and the ROS 2 bridge is enabled.

## Add Joint States in UI

1. Open the asset, which can be found by going to the Isaac Sim Content browser `Isaac Sim>Robots_Multiphysics>FrankaRobotics>FrankaPanda>franka>franka.usda`.
2. Go to **Window > Graph Editors > Action Graph** to create an Action graph.
3. Add the following OmniGraph nodes into the Action Graph:
   - **On Playback Tick** node to execute other graph nodes every simulation frame.
   - **Isaac Read Joint State** node to read joint states from the robot articulation.
   - **Isaac Read Simulation Time** node to read the simulation timestamp.
   - **ROS2 Context** node to provide the ROS 2 context to bridge nodes.
   - **ROS2 Publish Joint State** node to publish ROS 2 Joint States to the `/joint_states` topic.
   - **ROS2 Subscribe Joint State** node to subscribe to ROS 2 Joint States from the `/joint_command` topic.
   - **Articulation Controller** node to move the robot articulation according to commands received from the subscriber node.
4. Select the Isaac Read Joint State node and add the `/panda` robot articulation to the Prim Path input.
5. Select the Articulation Controller node, indicate the robot articulation you want to move by adding `/panda` to the targetPrim, or typing `/panda` in the robotPath field.
6. Connect the Tick output of the On Playback Tick node to the Exec In input of the Isaac Read Joint State, ROS2 Subscribe Joint State, and Articulation Controller nodes.
7. Connect the Isaac Read Joint State outputs to the matching ROS2 Publish Joint State inputs. Connect Read Sim Time to the publisher timestamp input. Connect ROS2 Context to the publisher and subscriber context inputs, as shown in the graph *(image: ROS 2 joint state Action Graph using Isaac Read Joint State)*.
8. Press **Play** to start publishing joint states to the `/joint_states` topic and subscribing commands on the `/joint_command` topic.

To test out the ROS 2 bridge, use the provided Python script to publish joint commands to the robot. In a ROS 2-sourced terminal:

```bash
ros2 run isaac_tutorials ros2_publisher.py
```

While the robot is moving, open a ROS 2-sourced terminal and check the joint state ROS 2 topic by running:

```bash
ros2 topic echo /joint_states
```

> **Note:** Articulation Root describes the beginning of an articulation tree, a collection of links and joints that makes up the robot in simulation. For fixed base robots like the franka, articulation root is specified at its root joint to world, and for move-able objects, the articulation root is specified at the rigid body with the deepest tree, typically the torso or chassis_link.

## Graph Shortcut

We provide a menu shortcut to build Joint State Publisher and Subscriber graphs with just a few clicks. Go to **Tools > Robotics > ROS 2 OmniGraphs > Joint States**. If you don't observe any ROS 2 graphs listed, you need to enable the ROS 2 bridge. A popup box will appear asking for the parameters needed to populate the graphs. You must provide the Graph Path, Node Namespace if there is one needed, and the prim that contains the Articulation Root API. If you are using the subscriber, you also have the option to add the Articulation Controller node needed to move the robot.

## Add Joint States in Extension

The same action done using the UI can also be done using a Python script. More details regarding the different workflows of using NVIDIA Isaac Sim can be found in Development Methods.

1. Open the asset, which can be found by going to the Isaac Sim Content browser and clicking `Isaac Sim>Robots_Multiphysics>FrankaRobotics>FrankaPanda>franka>franka.usda`.
2. Open Script Editor in **Window > Script Editor** and copy and paste the following code into it. This creates the same graph topology as the Joint States shortcut. If the robot appears other than `/panda` on the Stage Tree, make sure to match the Articulation Controller and Isaac Read Joint State nodes' targets to the robot's prim path.

```python
# --- TRUNCATED: the source paste ended partway through this snippet ---
import omni.graph.core as og
from pxr import Sdf

ROBOT_PRIM = "/panda"
GRAPH_PATH = "/Graph/ROS_JointStates"

og.Controller.edit(
    {"graph_path": GRAPH_PATH, "evaluator_name": "execution"},
    {
        og.Controller.Keys.CREATE_NODES: [
            ("OnPlaybackTick", "omni.graph.action.OnPlaybackTick"),
            ("ReadSimTime", "isaacsim.core.nodes.IsaacReadSimulationTime"),
            ("Context", "isaacsim.ros2.bridge.ROS2Context"),
            ("ReadJointState", "isaacsim.sensors.physics.IsaacReadJointState"),
            ("PublisherJointState", "isaacsim.ros2.bridge.ROS2PublishJointState"),
            ("SubscriberJointState", "isaacsim.ros2.bridge.ROS2SubscribeJointState"),
            ("ArticulationController", "isaacsim.core.nodes.IsaacArticulationController"),
        ],
        og.Controller.Keys.CONNECT: [
            ("OnPlaybackTick.outputs:tick", "ReadJointState.inputs:execIn"),
            ("ReadJointState.outputs:execOut", "PublisherJointState.inputs:execIn"),
            ("ReadJointState.outputs:jointNames", "PublisherJointState.inputs:jointNames"),
            ("ReadJointState.outputs:jointPositions", "PublisherJointState.inputs:jointPositions"),
            ("ReadJointState.outputs:jointVelocities", "PublisherJointState.inputs:jointVelocities"),
            ("ReadJointState.outputs:jointEfforts", "PublisherJointState.inputs:jointEfforts"),
            ("ReadJointState.outputs:jointDofTypes", "PublisherJointState.inputs:jointDofTypes"),
            # ... (missing)
```

*(Remainder of the page not received.)*
