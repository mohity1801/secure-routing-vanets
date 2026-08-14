# Base-paper Figures 11–15

These are reproducible replacements for Figures 11–15 of Sellami, Mchergui and
Alaya (2026). All six implemented baselines are shown: LEACH, LEACH-C, HEED,
PSO, GA and CSGD-NET.

```bash
# Needed only to create/refresh the genuine per-seed data for Figure 14.
python3 src/run_baseline_per_seed.py

# Regenerates all PNG and PDF figures from committed JSON artifacts.
python3 src/plot_baseline_figures.py
```

Figures 11, 12, 13 and 15 read the existing aggregate traces in
`results/baseline.json`; regenerating them does not rerun an experiment. Figure
14 reads `results/baseline_per_seed.json`, which preserves 30 independent
dead-node traces from the unchanged static-baseline methodology. Its bands are
pointwise, two-sided 95% Student-t confidence intervals using sample standard
deviation (`ddof=1`, 29 degrees of freedom), intersected with the feasible
0–100 node range.

Figure 11 is deliberately labelled **mean residual energy per node (J)**. The
base paper calls it energy consumption/total remaining energy, but its plotted
0–0.5 scale and Table 4 are per-node residual energy.

`manifest.json` records the exact input hashes, protocol set, round range and CI
method used to produce the figures.
