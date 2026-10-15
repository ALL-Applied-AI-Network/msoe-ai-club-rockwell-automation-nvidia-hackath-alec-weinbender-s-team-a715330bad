# data/

Local datasets. **Everything here except this README is gitignored.** Per the event's data-handling rules, raw data stays
unchanged, derived files are kept separate, and nothing large goes into git.

```text
data/
  raw/         Unmodified downloads from the Innovation Lab data folder or CSI collections (never edit in place)
  processed/   Cleaned files and labels derived from raw/
  synthetic/   Twin-generated data. Keep the generation settings and seed next to each set
  sample/      (optional) a small committable sample; un-ignore it explicitly in .gitignore if you add one
```

## How to get the data

- **Dataset 3 assets and digital twin:** <https://msoe-maic.com/library?article=Rockwell-NVIDIA-Fall-2026-Grasping-Sorting>
  (the twin is already vendored at `sim/fanuc_er4ia_sim/`).
- **Extra recordings, measurements or test sessions:** request in `#data-and-testbed-requests`, tag Shamar Webster
  (webste63@uwm.edu). See [../docs/references/collect-and-test-your-own-data.md](../docs/references/collect-and-test-your-own-data.md).

For every set you add, write down: who collected or generated it, when, how, and the terms under which it may be shared.

The web app's own runtime data (SQLite DB, uploads, generated CAD) lives in `app/data/`, not here.
