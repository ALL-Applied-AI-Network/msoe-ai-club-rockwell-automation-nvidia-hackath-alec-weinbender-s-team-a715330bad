"""PreToolUse hook: block Bash commands that look like they would drive the PHYSICAL FANUC arm.

Event rule: no commands to the physical arm or changes to its controller without the plant manager and mentor.
Mock/simulated launches (use_mock:=true, Isaac Sim) are fine. Exit code 2 blocks the call and shows stderr to Claude.
"""
import json, re, sys

PATTERNS = [
    (r"robot_ip\s*:=", "launches the FANUC ROS 2 driver against a real controller (robot_ip:=...)"),
    (r"use_mock\s*:=\s*false", "disables mock hardware (use_mock:=false)"),
    (r"\b192\.168\.1\.(100|101)\b", "targets the robot-controller subnet from the FANUC driver docs"),
]

try:
    event = json.load(sys.stdin)
except Exception:
    sys.exit(0)
cmd = (event.get("tool_input") or {}).get("command") or ""
for pat, why in PATTERNS:
    if re.search(pat, cmd, re.IGNORECASE):
        print(f"Blocked by .claude/hooks/guard_physical_robot.py: this command {why}. Commands to the physical "
              "arm are only allowed at CSI with the plant manager and mentor present. Use use_mock:=true or the "
              "Isaac Sim twin instead, or ask the user to run it themselves under supervision.", file=sys.stderr)
        sys.exit(2)
sys.exit(0)
