---
date: 2026-10-26
kind: sim
owner: Oliver Grudzinski (run by Claude Code from his laptop)
git_commit: 121b55d (the GB10's ~/repo and the laptop backend: the landing readout, the landing rule and the patience fix)
---

# The landing check in Isaac, and the M6 screw rerun with it

## Question

- Does the new landing readout measure a finger landing on the part?
- Why do the screw's results flip between runs: the vectorised path, the part, or contact?
- With landings scored as misses and the patience fix in, does a generated finger beat the stock fingers on the screw?

## Setup

- **Code:** `121b55d` on the GB10 (`~/repo`, sim server reinstalled, Isaac's pins put back). The previous copy is kept in
  `~/repo-4c9269f-20261026`. The laptop backend runs the same commit, migrated to 0008.
- **The landing rule:** a grasp that moved the part more than 1 mm or turned it more than 3° between the end of the
  approach and the end of the descent (jaws still open) scores as a miss (`api/models/outcome.py`).
- **Reference session, 22:18–22:32, `--envs 1`** (`~/repo/runs/ref_session_20261026.sh`, outputs in
  `~/repo/runs/ref_20261026/`):
  - GPU test plan stage 4: `flat_pads.json` (stock, `pad_x0` with 1 mm slack per side, `pad_x2` with 3 mm) on the
    cube, 81-point grid at yaw 0.
  - The screw's stock batch, twice. It's the request the app sent for stock in EXP-0002: grasp g0 (the shank, 90°,
    jaws closing to 0.7 mm), the 963-point final grid, the twin's grip force. It was rebuilt with the app's own payload
    code.
- **Then on `--envs 64 --device cpu`, from 22:33:**
  - **EXP-0003:** the library evaluation again (stock, FNG-0002 imprint), same spec as EXP-0002.
  - **A control batch:** the stock fingers stopping 40 mm above the table (`tip_height_mm: 40`), so nothing can touch
    the screw. It shows how far an untouched screw moves.
  - **EXP-0004:** the generation job again, same spec as EXP-0001 (V-pad, budget 128, 12 Sobol starts, batch 4,
    patience 12).
  - The three shared the sim server until about 22:50, which slowed EXP-0004's rounds 0 and 1.
- **Error model:** the cell's 3 mm / 8° (a placeholder) throughout. Nobody else was logged in, and there were no other
  GPU processes.

## Results

### The landing readout measures landings (stage 4, cube, `--envs 1`)

Along +dx, the shift a design gave the cube before the jaws closed:

| dx (mm) | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Stock (mm) | 0 | 0 | 0 | 0.01 | 0.98 | 1.91 | 2.99 | 6.23 | 4.18 |
| `pad_x0`, 1 mm slack (mm) | 0 | 0 | 1.00 | 2.03 | 3.00 | 4.03 | 4.98 | 0.08 (turned 4.9°) | 0.09 (4.7°) |
| `pad_x2`, 3 mm slack (mm) | 0 | 0 | 0 | 0 | 1.00 | 2.02 | 3.01 | 4.03 | 7.60 (49.5°) |

- **The pads push the cube by exactly the offset minus their slack.** That's what a pad face landing on the cube and
  dragging it should do.
- **With the rule, stage 4's sanity check passes.** It has failed since 2026-10-20, when tight and loose pads scored
  55 and 56 of 81 because a pad landing on the cube still counted as a hold.
  - `pad_x0` stops counting from dx = 3 mm, and `pad_x2` from dx = 5 mm.
  - Before the rule, both held out to ±8 mm.
- Held, and held after a landing: stock 58 / 16 of 81, `pad_x0` 55 / 29, `pad_x2` 56 / 14.

### An untouched screw doesn't move (control batch, `--envs 64 --device cpu`)

With the fingers stopping 40 mm above the table, the screw's shift and turn were **exactly 0 at all 963 offsets**.
Whatever moves it in a real grasp is the fingers.

### The screw's flips come from the part, not from the vectorised path

The stock fingers on the screw, 963-point final grid, 3 mm / 8°, scored without the landing rule:

| Run | Path | Held | Predicted |
| --- | --- | ---: | ---: |
| Reference a | `--envs 1` | 750 | 88.5% |
| Reference b | `--envs 1` | 774 | 90.8% |
| EXP-0001 | `--envs 64 --device cpu` | 735 | 87.2% |
| EXP-0002 | `--envs 64 --device cpu` | 744 | 88.6% |

**Agreement between runs:**

- **The two reference runs agree on 81.1% of points.** For comparison:
  - reference a against EXP-0001: 80.2%;
  - reference a against EXP-0002: 79.0%;
  - EXP-0001 against EXP-0002: 77.5%.
- So the reference path is barely more repeatable than the vectorised one. The screw is the cause.
- Points that flip between the reference runs, by distance from the centre: 6 of 195 within 2 mm, 14 of 192 at
  2.5–4 mm, 39 of 192 at 4.5–6 mm, and 123 of 384 at 6.5–12 mm.

**The fingers touch the screw, differently each run:**

- About 37% of grasps moved it past 1 mm or 3°: 361 of 963 in reference a, 363 in reference b.
- At the median it doesn't move at all. But within 1 mm of the centre it shifted up to 2.8 mm and turned up to 33–47°.
- At the exact centre (yaw 0), run a turned it 5.5° and run b didn't move it.
- How far it moves at a point barely repeats between runs: the correlation over all points is 0.33 for the turn and
  0.24 for the shift.
- Of the points that flipped between the reference runs, 133 of 182 involve a landing in one run or the other.
- **In the clip of stock at the centre, the screw sits inside the stock blades' round socket,** between the hooked tips,
  as they come down. It's a tight fit, so small differences decide whether a blade brushes it.

**The rule doesn't make the screw repeatable:** the two reference runs agree on 78.5% of points with it, against 81.1%
without. The landings themselves vary from run to run.

### EXP-0003: the library evaluation, with landings as misses

| Rank | Finger | Predicted at 3 mm / 8° | Same finger in EXP-0002 (no landing rule) |
| --- | --- | ---: | ---: |
| 1 | FNG-0001 stock | **63.4%** | 88.6% |
| 2 | FNG-0002 imprint | 49.1% | 76.0% |

- **674 of the 1,766 grasps the sim held count as misses:** a finger moved the screw before the jaws closed.
- The success-vs-σ curve (0.5 / 1 / 2 / 3 / 4 / 5 mm):
  - stock: 80.7 / 74.9 / 69.8 / 63.4 / 55.4 / 47.3%;
  - imprint: 53.5 / 55.5 / 54.3 / 49.1 / 43.6 / 38.1%.
- Stock now loses about 15 points even at 0.5 mm, which is the landings near the centre.

### EXP-0004: generation with the patience fix and the rule

- **The search ran 32 designs and stopped on patience.** BO found its best (65.8% on the search grid) in round 2.
  Rounds 3, 4 and 5 (12 BO designs) didn't beat it by 0.5 points, so it stopped.
  - EXP-0001, before the fix, ran 16 designs, with only 4 from BO.
- **Search-grid baselines in the same rounds:** stock 63.0%, imprint 44.1%.
- **The best design pushes slack to its limit:** pad 10.6 mm wide, slack 5.5 mm (the maximum), tip 1.7 mm above the
  table, no lead-in.
- **Rounds took 153–155 s once it had the sim to itself,** about 6.3 grasps/s. Rounds 0 and 1 took 729 s and 452 s
  while it shared the sim.
- **The final dense-grid test (D1–D3, stock, imprint) puts stock ahead.** These are 963 points each with the landing
  rule on. "Held" counts grasps that held without a landing.

  | Design | Predicted at 3 mm / 8° | Held | Capture radius | Params |
  | --- | ---: | ---: | ---: | --- |
  | **Stock** | **66.9%** | 518 | 0 mm | |
  | D1 | 62.9% | 516 | none | pad 10.6, slack 5.5, tip 1.67, lead-in 0 mm |
  | D2 | 62.4% | 514 | none | pad 10.6, slack 5.5, tip 2.21, lead-in 0 mm |
  | D3 | 61.1% | 504 | 0 mm | pad 10.6, slack 5.5, tip 1.90, lead-in 0 mm |
  | Imprint | 46.6% | 387 | none | |

  - **The search picked a lucky design.** D1 scored 65.8% on the search grid and 62.9% on the dense one. That's the
    winner's curse on a noisy part: the best of 32 noisy scores is biased upward.
  - **Stock scored 66.9% here and 63.4% in EXP-0003.** Same finger, same grid, 3.5 points apart: the noise again.
  - **D1–D3 are one design:** the same pad and slack, only the tip height varies, at 1.7–2.2 mm.
  - **2,767 of 7,391 held grasps counted as misses** across the job's final test.
- **Time:** 2,590 s (43 min), against a 5,688 s estimate made for the full budget. The run stopped on patience at 32
  designs.
- **The VPN dropped once:**
  - The MSOE VPN went down at 23:16:40, during the final test.
  - The batch finished on the GB10 at 23:17:06, under its idempotency key.
  - At 23:17:38 the app found the sim answering again and resent the batch, and the server answered from the run it
    had already made.
  - Nothing was lost or simulated twice.

**Success vs σ with the landing rule:**
[chart](2026-10-26-screw-success-vs-sigma-landing.png), [CSV](2026-10-26-screw-success-vs-sigma-landing.csv). It's
re-scored from EXP-0004 and EXP-0003, yaw σ 8° throughout. The two stock runs are drawn as a band.

| σ (mm) | 0.5 | 1 | 2 | 3 | 4 | 4.5 | 5 | 5.5 | 6 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Stock, EXP-0004 | 87.0 | 81.2 | 74.6 | 66.9 | 58.2 | 53.8 | 49.6 | 45.5 | 41.8 |
| Stock, EXP-0003 | 80.7 | 74.9 | 69.8 | 63.4 | 55.4 | 51.3 | 47.3 | 43.5 | 39.9 |
| D1, EXP-0004 | 73.6 | 71.3 | 68.3 | 62.9 | 57.0 | 53.8 | 50.5 | 47.2 | 44.0 |
| Imprint, EXP-0003 | 53.5 | 55.5 | 54.3 | 49.1 | 43.6 | 40.8 | 38.1 | 35.4 | 32.8 |

- **Below 4.5 mm, stock is better than D1.** At 0.5 mm it's 7–13 points ahead, because D1 brushes the screw near the
  centre more than stock does.
- **D1 matches stock's better run at 4.5 mm,** and leads both runs from 5 mm. At 6 mm it leads by 2.3–4.1 points, which
  is about the size of the noise. So it's a lean, not a win.
- **Clips 6–8 (`app/data/outputs/bc42930e7d/clips/`):** D1, STOCK and IMP at the centre, closeup and side views. All
  three held, matching their stored results.

## Why the stock fingers are hard to beat on the screw

Partly measured, partly reasoned from the geometry and the twin's settings:

1. **The shank is in the stock fingers' sweet spot.**
   - The blades open 12 mm between their straight faces and 16 mm at the hooked tips, and the shank is Ø6. So a grasp
     that lands 3–5 mm off along the closing direction still closes onto it.
   - Along the screw's length, the shank gives about 26 mm to grip, so error that way rarely matters.
   - Measured: stock holds about 95% at 0.5–1 mm of error and 87–91% at 3 mm, without the landing rule.
2. **The stroke caps any finger.** Each jaw moves only 6 mm, and a custom pad must still close onto a 6 mm shank, so
   its slack can't grow much past what the stock blades already have.
   - Every good design found tonight pushed slack to the maximum: D1 of EXP-0001 at 5.4 mm, EXP-0004's best at 5.5 mm.
   - On this part a generated finger can only win on details: where its pads meet the shank, its tip height, and not
     brushing the screw on the way down.
   - This is CONTEXT.md risk 2 (the tiny stroke) showing up in the results.
3. **The hooked tips act as a funnel.** The tips flare wider than the faces, and the round socket between them (made for
   an AA cell) seats a round shank. The optimizer kept choosing no lead-in, which suggests the stock tips already do
   that job.
4. **The twin gives the stock fingers more friction than a printed finger.**
   - The stock tips have the twin's soft high-friction material: 1.5 static, 1.3 sliding.
   - A custom finger is simulated with the part's estimated friction against printed PLA: 0.4 / 0.3.
   - The server averages the two materials in contact, so the stock fingers grip the screw at about 0.95 static and a
     printed finger at 0.4.
   - For a 7.5 g screw this shouldn't decide whether it's held: 0.4 × 2.5 N per jaw is about 2 N against 0.07 N of
     weight. It may help stock pull the screw into a centred grip.
   - Neither value is measured. That needs a tilt test of the printed material, and a look at the real stock tips.
5. **Where stock does lose: landing on the screw.** The snug socket means the blades often brush the screw on the way
   down (above). Counting that as a miss drops stock from about 88% to 63%. That's the opening for a custom finger that
   clears the part before it closes.

## Failures observed

- **The screw's outcomes aren't repeatable on either path.** About 1 grid point in 5 flips between runs, mostly past
  4.5 mm, and mostly where a finger touched the screw. With the landing rule it's about the same (78.5% agreement).
  Two runs of one finger differ by 1.4–2.3 points, so smaller gaps between fingers aren't real.
- **The 1 mm / 3° thresholds:** an untouched part moves exactly 0, so any motion means contact, and the thresholds are
  well above that floor. Whether a brush that size knocks a real screw away is still a guess.

## Artifacts

- **GB10:** `~/repo/runs/ref_20261026/`: `session.log`, `flat_pads_grid.json`, `screw_stock_a.json`,
  `screw_stock_b.json`, `screw_hover_envs64.json`, each with its request and response.
  - The batch files: `~/repo/runs/screw_stock_final_batch.json` and `screw_hover_batch.json`.
- **App database:** `app/data/app.db` on Oliver's laptop. EXP-0003 is `f706a06d16` and EXP-0004 is `bc42930e7d`.

## Next

- **For the screw, keep the stock fingers.** That's the library-first answer. In the twin, no generated V-pad beats
  them at the cell's error, and their lead below 4.5 mm is bigger than the noise.
- If we want to claim D1's lean at 5–6 mm of error, repeat its final test against stock two or three times first.
- For a part where a custom finger should clearly win, try one the stock fingers can't open around: the vial cap's plug
  (Ø20.8–23.6) or the 16 mm cube.
