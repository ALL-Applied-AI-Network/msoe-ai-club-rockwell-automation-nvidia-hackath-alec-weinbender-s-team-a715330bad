---
title: Windows local setup and mock optimizer verification
source: local commands and app/data/worker.log
author: Team development notes
received: 2026-10-21
date: 2026-10-21
kind: other
owner: local development setup
git_commit: b69befd
---

# Windows local setup verification

This checks software operation only. No Isaac simulation, GPU physics, or physical robot was exercised.

## Setup

- Host: MICHAEL-SERVER, Windows, AMD Ryzen 5 2600X.
- uv 0.13.4, Python 3.12.15, locked CPU torch 2.14.1, BoTorch 0.18.1 and CadQuery 2.8.0.
- Root `.env`: mock LLM, simulator and compute. No algorithm or lockfile changes.
- Part: generated 10 x 10 x 10 mm STL cube, millimetres, PLA, resting pose index 0.
- Default seeded cell profile, default task and error model, grasp angle 0 degrees, seed 0, budget 14.
- Baselines: stock and imprint. Search and final grids use the existing defaults.

## Results

- HTTP upload, part confirmation and job creation succeeded against the live API.
- Job `065d6f52ca` (`EXP-0001`, name `Local setup check (MOCK)`) progressed through queued, running, finalizing and done.
- Round zero evaluated 12 Sobol candidates and both baselines; two subsequent BO rounds evaluated one candidate each. Final validation included three finalists and both baselines. The job finished with 21 stored trial rows.
- Worker log recorded completion at 11:13:39 America/Chicago, about 10 seconds after worker execution began. This is software/mock timing only.
- D1 STEP, left and right STL and print-sheet PDF were produced; the worker reported no blocking export-check failures. The review gate remains in place.
- Verification completed: 11 optimizer tests passed, then all 893 offline tests passed in 267.80 seconds. Ruff lint, formatting checks and the frontend build also passed. Isaac integration tests were not run.
- Mock scores are deliberately omitted here: geometric capture scores do not measure grasp reliability.

## Failures and limitations

- Initial optimizer and full-suite collection failed loading `torch/lib/c10.dll` with WinError 1114. The Visual C++ runtime was 14.29.30153. Silent installation of the signed Microsoft runtime failed to elevate (error 1459); the user installed it through their desktop. After the update to 14.44.35211, torch imported and the optimizer tests passed.
- GB10 initially failed DNS resolution. After GlobalProtect was reconnected, the hostname resolved over the VPN route, but SSH port 22 timed out. No remote authentication, server inspection, simulator run or restart occurred.
- The locked frontend's npm audit reports an affected Vite dependency. Dependencies were kept locked; see the setup assessment for details.

## Artifacts

- Local SQLite records: `app/data/app.db`, job `065d6f52ca`.
- Local worker log: `app/data/worker.log`.
- Generated exports: `app/data/outputs/065d6f52ca/`.
- These runtime artifacts are ignored by Git and are not committed.
- Setup commands and proposed BO/Sobol benchmark: [assessment](../notes/bo-assessment.md).
