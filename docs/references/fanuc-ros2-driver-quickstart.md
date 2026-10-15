---
title: FANUC ROS 2 Driver — Quick Start
source: FANUC ROS 2 Driver Documentation (docs version main / Jazzy), "Quick Start" page; code at https://github.com/FANUC-CORPORATION/fanuc_driver
author: FANUC CORPORATION
received: 2026-10-15
kind: reference
linked_from: 03-dataset-3-grasping-sorting.md ("Official FANUC ROS 2 driver quickstart")
---

# FANUC ROS 2 Driver — Quick Start

> **Our notes (not part of the source):**
>
> - The bundled `fanuc_moveit_config` only covers **CRX** models. Our robot is an **ER-4iA**, so using MoveIt on it would need our own MoveIt config package.
> - Physical-hardware use needs controller options (J519 Stream Motion + R912 Remote Motion, or S636) and changes to network/controller settings. **We may not touch the physical controller or send commands to the arm without the plant manager and mentor** (see [collect-and-test-your-own-data.md](collect-and-test-your-own-data.md)). Treat everything past "Launching with Mock Hardware" as reference for CSI staff, not for us to run.
> - Mock hardware (`use_mock:=true`) is safe to use locally for planning experiments.

This repository hosts the source code of the FANUC ROS 2 Driver project, a ros2_control high-bandwidth streaming driver. This project will allow you to develop a ROS 2 application to control a FANUC virtual or real robot.

> **Note:** This guide assumes basic familiarity with ROS 2, Ubuntu, and FANUC hardware.

## System Requirements

See the system requirements page.

## 1. Install Dependencies

### Set up the ROS 2 Environment

Follow the official ROS 2 Installation Guide for the Desktop Install of **ROS 2 Jazzy**.

### Configure the ROS 2 Environment

We recommend performing the following tasks in the ROS 2 Configuring Environment:

- Add sourcing to your shell startup script
- The `ROS_LOCALHOST_ONLY` variable

## 2. Install FANUC software packages

Choose one of the following installation methods:

- Source Build of FANUC Packages
- Debian Install of FANUC Packages

### Method 1: Source Build of FANUC Packages

```bash
echo "Installing and configuring git-lfs"
sudo apt install git-lfs
git lfs install

echo "Checking out GitHub repositories"
mkdir ~/ws_fanuc/src -p
cd ~/ws_fanuc/src
git clone https://github.com/FANUC-CORPORATION/fanuc_description.git
git clone --branch main --single-branch --recurse-submodules https://github.com/FANUC-CORPORATION/fanuc_driver.git

echo "Installing FANUC dependencies"
cd ~/ws_fanuc
sudo apt update
rosdep update
rosdep install --ignore-src --from-paths src -y

echo "Building FANUC libraries"
colcon build --symlink-install --cmake-args -DBUILD_TESTING=1 -DBUILD_EXAMPLES=1
```

### Method 2: Debian Install of FANUC Packages

Debian packages will be provided at a future date.

## 3. Launching URDF Visualization

The `view_crx` launch file visualizes a URDF model in RViz and provides slider bars to visualize a specific joint state.

```bash
source /opt/ros/jazzy/setup.bash
source ~/ws_fanuc/install/setup.bash
ros2 launch fanuc_crx_description view_crx.launch.py robot_model:=crx10ia
```

*(Screenshot: starting RViz view after running `view_crx.launch.py`.)*

## 4. Create Moveit Config

`fanuc_moveit_config` is an example MoveIt configuration package which supports the following robot models:

- CRX-3iA
- CRX-5iA
- CRX-10iA
- CRX-10iA/L
- CRX-20iA/L
- CRX-30iA
- CRX/30-18A

When you want to use other models, create your MoveIt configuration package following this page.

## 5. Launching with Mock Hardware

The `fanuc_moveit` launch file starts ROS processes to control a URDF model using ros2_control and MoveIt2.

```bash
source /opt/ros/jazzy/setup.bash
source ~/ws_fanuc/install/setup.bash
ros2 launch fanuc_moveit_config fanuc_moveit.launch.py robot_model:=crx10ia use_mock:=true
```

RViz will launch with a visualization of the CRX-10iA.

Drag the 3-D arrows to set a goal pose for the robot. Then click **Plan & Execute** to simulate the robot planning and executing a trajectory to the goal.

### Dynamically scaling trajectory execution

The `fanuc_moveit` launch file configures a Scaled Joint Trajectory Controller (SJTC), which enables us to slow down and pause trajectories while they are executed.

Set the trajectory speed scaling factor to 10% by Slider Publisher value. Drag the IMarker to a new location and click Plan & Execute. The robot will move slowly to the goal. Now, set the speed scaling factor to 0% and see it pause its motion. Set it back to 100% and the robot will complete the remainder of the trajectory at its nominal speed.

## 6. Launching with Physical Hardware

Now we will use the same SJTC on the physical hardware. We will use the same `fanuc_moveit` launch file, but provide a different set of arguments that will use the physical hardware interface instead of mock hardware.

### Robot Controller Setup

Requires software version:

- R-30iB Plus, R-30iB Mate Plus: V9.40P/81 or later
- R-30iB Mini Plus: V9.40P/77 or later
- R-50iA series: V10.10P/26 or later

Requires software options:

- J519 Stream Motion and R912 Remote Motion, **or**
- S636 External Control Package (includes J519 and R912)

#### Confirm that the required robot controller software is installed

1. Display FULL MENUS.
2. Select STATUS.
3. Select Version ID.
4. Select CONFIG.

> **Note:** Software options are listed in alphabetical order.

Cursor until you find Stream Motion J519 and Remote Motion R912 or S636 External Control Package.

If you cannot find Stream Motion J519 and Remote Motion R912, or S636 External Control Package, contact FANUC to obtain the software option.

### Establish Payload Settings

Accurately setting your robot's payload is important.

**Prior to ROS 2 driver v2.0.0 and controller software V9.40P/84**, changing payload requires the client to execute the following steps:

1. Bring the robot to a stop.
2. Deactivate the hardware interface.
3. Change the payload schedule.
4. Reactivate the hardware interface.
5. Resume your application.

**Later than ROS 2 driver v2.0.0 and controller software V9.40P/84**, you can use a ROS 2 service to change payload value or payload compensation on the fly. See "Setting payload value and payload compensation".

### Driver Network Configuration

The FANUC ROS 2 Driver requires a network connection to the robot, which can be either port 1 or port 2. It is recommended that the communication between the driver and the robot be on a port that is isolated from all other Ethernet communications.

First, we will set IP addresses for each of the Ethernet connections.

If your computer has two network interfaces (one to connect to the Internet and another to connect to robot controller) each needs a different connection profile. To set these up, click the arrow at the upper right corner of the screen, and then click Settings > Network.

1. Unplug the Ethernet cable between the computer and your network infrastructure. One of the two wired interfaces will now show up as "Cable unplugged." Click the gear icon next to that wired adapter.
2. Under the Identity tab, give this profile a name (like "Internet").
3. Click Apply to accept the default values for the other settings.
4. Plug the Ethernet cable back in.
5. Now, click the gear icon next to the other network adapter.
6. Under the Identity tab, assign a name to the connection profile, such as "Robot".
7. Under the IPv4 tab, select Manual as the IPv4 Method.
8. Enter `192.168.1.101` for the Address, and `255.255.255.0` for the Netmask.
9. Click Apply.

### Robot Network Configuration

After defining your port, you now need to configure that port using the Host Communication screen (configure the robot's static IP).

### Robot Controller Status

Confirm that the following conditions are met:

- The operation mode is AUTO.
- All alarms are removed.
- The teach pendant is disabled (OFF). For a Tablet TP: correct is OFF, wrong is ON.

### Launching CRX-10iA with Driver

```bash
source /opt/ros/jazzy/setup.bash
source ~/ws_fanuc/install/setup.bash
ros2 launch fanuc_moveit_config fanuc_moveit.launch.py robot_model:=crx10ia robot_ip:="192.168.1.100"
```

You can command motion using the same IMarker workflow used earlier.

> **Note:** The robot controller may raise the alarm `RMIT-016 Please Cycle Power.` on the first connection. In this case, repower the robot controller and the fanuc_driver so that the robot controller can automatically disable the Hot start for Remote Motion.

See Controller Usage to learn more about the available controllers.

### Setting I/O Values

To monitor I/O status from pendant, follow these instructions on the pendant:

1. Click on three lines to open pendant side menu.
2. Then choose the I/O option.
3. The window will show all the I/O types and their current status.

Now change a bool I/O via the ROS 2 CLI:

```bash
ros2 service call /fanuc_gpio_controller/set_bool_io fanuc_msgs/srv/SetBoolIO "{io_type: {type: 'DO'}, index: 1, value: true}"
```

The pendant will now show the I/O Status as ON (DO1 port is on).

> **Note:** See Controller Customization to learn more about monitoring and setting I/O via ros2_control and the command line.

## Obtain Support

Contact your local FANUC sales representative. To expedite your request, please provide information such as robot model, configuration, and application, so we can determine how best to support your request.

*© Copyright 2026, FANUC CORPORATION.*
