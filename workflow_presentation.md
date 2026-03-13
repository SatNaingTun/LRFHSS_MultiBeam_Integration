---
marp: true
---

# LRFHSS Multi-Beam Integration Workflow

## Slide 1 - Title
- Project: `LRFHSS_MultiBeam_Integration`
- Topic: End-to-end workflow for heavy-load LR-FHSS evaluation
- Scope: Orbit + visibility + traffic + demodulator constraints + decoding performance

<!-- Presenter note: Introduce the scope and emphasize this is a full pipeline from satellite geometry to decoding KPIs. -->

---

## Slide 2 - Objective
- Evaluate LR-FHSS decoding performance under increasing node load
- Measure effect of demodulator limits on decoded payloads
- Record collisions, tracked transmissions, and decoded bytes
- Produce reproducible metrics and plots for analysis

<!-- Presenter note: State that the main question is where performance breaks first under heavy load. -->

---

## Slide 3 - End-to-End Workflow
1. Initialize simulation parameters
2. Compute satellite orbit
3. Generate visibility windows
4. Generate IoT nodes
5. Assign LR-FHSS packets
6. Check satellite visibility
7. Select satellite power mode
8. Transmit fragments
9. Detect collisions
10. Allocate demodulators
11. Baseline packet decoding
12. Store metrics
13. Generate performance plots

<!-- Presenter note: Walk through quickly and mention modularity for future extensions. -->

---

## Slide 4 - Inputs and Configuration
- Entry script: `run_integration.py`
- Default node list: `0, 1, 5, 10, 20, 50, 100, 150, 200, 300, 500, 800, 1000, 1200, 1500`
- Example demodulator options: `10, 100, 1000` (or custom list with `--demods`)
- Seeded runs for reproducibility (`--seed`, default `42`)
- External dependencies auto-bootstrapped when missing:
  - `Multi-Beam-LEO-Framework`
  - `LR-FHSS_LEO`

<!-- Presenter note: Highlight reproducibility and zero-manual setup from dependency bootstrap. -->

---

## Slide 5 - Power Mode Logic
```python
if nodes == 0: mode = "sleep"
elif nodes < 200: mode = "idle"
else: mode = "busy"
```
- `sleep`: allocate 0 demodulators
- `idle` and `busy`: allocate requested demodulators
- Power mode is selected per node-load point

<!-- Presenter note: Explain that this is a simple policy baseline and can be replaced by smarter adaptive policies. -->

---

## Slide 6 - Core Simulation Loop
- For each node load:
  - Create node list and packet count
  - Apply visibility gate (if not visible, transmissions are zero)
  - For each requested demodulator count:
    - Allocate demods based on power mode
    - Run baseline decoding
    - Capture outputs: decoded payloads, tracked txs, decoded bytes, collisions

<!-- Presenter note: Emphasize this loop is the experiment matrix: nodes x demods. -->

---

## Slide 7 - Outputs and Artifacts
- Metrics:
  - `results/heavy_load/heavy_load_metrics.json`
  - `results/heavy_load/heavy_load_metrics.csv`
- Summaries:
  - `results/heavy_load/workflow_summary.json`
  - `results/heavy_load/heavy_load_summary.json`
- Plots:
  - `results/heavy_load/heavy_load_demodulator_constraints.png`
  - `results/heavy_load/decoded_payloads_by_power_mode.png`

<!-- Presenter note: Mention that CSV supports post-analysis while PNG enables immediate reporting. -->

---

## Slide 8 - Current Run Snapshot (from existing results)
- Records in CSV: `108`
- Node range in data: `0` to `1500`
- Demodulator counts evaluated: `10, 30, 50, 70, 100, 300, 500, 700, 1000`
- Power modes observed: `sleep`, `idle`, `busy`
- Visibility window example: frame `13052` to `77074`

<!-- Presenter note: Use this slide to confirm coverage and reassure audience the sweep is broad. -->

---

## Slide 9 - Observed Trend Summary
- Increasing demodulator capacity generally improves decoded payloads at low to moderate load
- At high load, decoded payloads saturate or drop due to contention/collisions
- Best observed decoded payloads in this dataset occur around mid-high demodulator counts (not always max demods)
- Very high node counts (for example `700+`) can drive decoded payloads close to zero in baseline mode

<!-- Presenter note: Stress that collision behavior, not only demod budget, dominates in heavy-load regimes. -->

---

## Slide 10 - How to Run
```powershell
python run_integration.py
```

```powershell
python run_integration.py --nodes 0 2 7 15 40 90 180 260 400 700 1000 1500 --demods 10 30 50 70 100 300 500 700 1000
```

<!-- Presenter note: Mention first command for default execution and second for custom sweeps. -->

---

## Slide 11 - Recommendations
- Add multiple runs per point (`runs_per_point > 1`) to reduce randomness
- Compare baseline vs early decode/early drop in the same workflow run
- Include throughput efficiency and collision rate plots per power mode
- Add automated regression thresholds for CI checks

<!-- Presenter note: Position these as actionable next steps for stronger experimental confidence. -->

---

## Slide 12 - Conclusion
- Workflow is modular, reproducible, and suitable for scaling experiments
- Main bottleneck under heavy load is contention, not only demodulator count
- Existing outputs are ready for performance reporting and design tuning

<!-- Presenter note: End by tying technical findings to practical optimization direction. -->
