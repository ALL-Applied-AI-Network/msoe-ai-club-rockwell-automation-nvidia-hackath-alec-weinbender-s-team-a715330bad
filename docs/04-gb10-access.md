---
title: MSOE GB10 access
source: email from Riley (NVIDIA) to the team, confirming access to an MSOE GB10 machine
author: Riley, NVIDIA (driley@nvidia.com)
received: 2026-10-20
kind: event
---

# MSOE GB10 access

> **Our notes (not part of the source):**
>
> - **The password is redacted here.** It's in the original email. Never put it in the repo, Slack, scripts or `.env`;
>   use SSH keys instead ([GPU test plan, 0.2](notes/gpu-test-plan.md#02-msoe-gb10-free-shared-set-up)).
> - The GB10 is ARM64 (the DGX Spark platform). Isaac Sim 6.0.1 is installed on the team account from NVIDIA's aarch64
>   pip wheels (2026-10-20). It needs the **R580 driver** the machine has (580.178.04): NVIDIA reports R590+ drivers crash
>   it at RTX startup. Check `nvidia-smi` before a session. We can't change the driver from a team account.
> - The machine is **shared with other teams**: they can reach its `127.0.0.1` ports, and the GPU may be busy.

Hello-

Thank you for requesting access to one of the MSOE GB10 machines. Access is set up by default via ssh. To access the
machine, you need to be connected to the MSOE VPN and then in your preferred shell you can enter:

```bash
ssh hackathon11@spark1.ai.msoe.edu
```

The username for your team is hackathon11 and the password is: *(redacted: see the original email)*

Your account should allow you to install software on the machine accessible to your team.

Other teams will also be assigned to this machine, so if you are getting unexpected errors, feel free to check the
following:

- `who`: Who is logged into the machine
- `nvidia-smi`: GPU utilization/processes

If you routinely have issues getting enough resources on your GB 10 to run your jobs, please reach out to
driley@nvidia.com to investigate.

--Riley
