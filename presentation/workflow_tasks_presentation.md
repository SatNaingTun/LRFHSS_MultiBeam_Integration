---
marp: true
theme: default
paginate: true
title: LR-FHSS Multi-Beam Integration Workflow
description: End-to-end workflow tasks and data flow explanation
---

# LR-FHSS Multi-Beam Integration
## Workflow Task Breakdown

- Project: `LRFHSS_MultiBeam_Integration`
- Entry point: `main.py`
- Core execution: `workflow.py::run_workflow(...)`
- Output root (default): `results/lrfhss_communication`

---

# Overall Workflow (High-Level)

1. Parse CLI configuration and validate reference paths.
2. Build node/demod candidate sets.
3. Propagate one-orbit satellite trajectory.
4. Estimate coverage and device/demod capacity per step.
5. Filter infeasible node/demod options.
6. For each country and step, run LR-FHSS reference-series mapping.
7. Export stepwise CSVs, country averages, plot, and JSON summary.

---

# Task 1: Parse Inputs and Initialize

- File: `main.py`
- Function: `parse_args()` and `main()`
- Responsibilities:
  - Read workflow arguments (`--nodes`, `--demods`, `--scenario-steps`, etc.).
  - Resolve external dependency paths (`Multi-Beam-LEO-Framework`, `lr-fhss_seq-families`).
  - Auto-run `ensure_reference_paths.py` when roots are missing.
  - Call `run_workflow(...)` with normalized arguments.

---

# Task 2: Build Candidate Loads

- File: `workflow.py`
- Helpers: `_build_node_loads(...)`, `_normalize_demods(...)`
- Responsibilities:
  - Convert explicit or log-spaced node list into unique positive integers.
  - Normalize demodulator options into sorted positive unique values.
  - Validate that the simulation has valid node and demod search spaces.

---

# Task 3: Select Valid LR-FHSS Reference Demods

- File: `workflow.py`
- Function: `list_available_demod_counts(...)`
- Responsibilities:
  - Read available demodulator counts from reference CSV.
  - Constrain runtime simulation to demod values that exist in measured data.
  - Fail fast if reference CSV contains no usable rows.

---

# Task 4: Load Multi-Beam Modules and Orbit State

- Files:
  - `workflow.py`
  - `workflow_tasks/orbit_visibility.py`
- Functions:
  - `load_multi_beam_modules(...)`
  - `compute_satellite_orbit(...)`
  - `compute_orbit_parameters(...)`
- Responsibilities:
  - Initialize geometry/simulation modules.
  - Propagate Kepler-based orbit states for required time horizon.
  - Compute derived orbit metrics (altitude, speed, inclination).

---

# Task 5: One-Orbit Ground Track and Coverage Export

- Files:
  - `workflow.py`
  - `coverage_population.py`
- Function: `export_coverage_population_csv(...)`
- Responsibilities:
  - Build one-orbit ground track arrays (lat/lon).
  - Estimate country-level covered adult population.
  - Convert population estimate to device and demod capacity.
  - Export:
    - `csv/coverage_population_devices.csv`
    - `csv/coverage_track_trace.csv`

---

# Task 6: Coverage Constraint Check

- File: `workflow_tasks/lrfhss_flowtask.py`
- Function: `_check_nodes_and_demods_for_coverage(...)`
- Responsibilities:
  - Compare requested nodes/demods against coverage-constrained totals.
  - Split options into in-coverage and out-of-coverage groups.
  - Stop workflow if no feasible options remain.

---

# Task 7: Load Per-Step and Per-Country Inputs

- File: `workflow_tasks/lrfhss_flowtask.py`
- Functions:
  - `_load_covered_countries(...)`
  - `_load_trace_steps(...)`
- Responsibilities:
  - Read countries currently in coverage and their share ratios.
  - Read each orbital step with satellite position and total estimated capacity.
  - Create the base dataset for country-by-step simulation.

---

# Task 8: Stepwise Country Allocation

- File: `workflow.py`
- Responsibilities:
  - For each rotation step and each covered country:
    - Scale total devices/demods by country coverage share.
    - Keep only feasible node/demod options.
    - Use stable seeded randomness per `(seed, step, country)`.
  - Produce reproducible but time-varying allocations.

---

# Task 9: Map to Reference Series and Decode Metrics

- Files:
  - `workflow.py`
  - `workflow_tasks/lrfhss_communication.py`
  - `workflow_tasks/lrfhss_flowtask.py`
- Functions:
  - `_select_available_demod(...)`
  - `build_comparison_series(...)`
  - `_extract_series_value_for_nodes(...)`
- Responsibilities:
  - Map requested demodulators to nearest available reference demod.
  - Reuse cached reference series for performance.
  - Extract sent packets and decoded payload values for selected node load.

---

# Task 10: Persist Stepwise Outputs

- File: `workflow.py`
- Responsibilities:
  - Write country-step records to:
    - `covered_countries_lrfhss_stepwise_results.csv`
  - Emit per-country CSV files under:
    - `country_csv/<ISO3>_<Country>_lrfhss_stepwise.csv`
  - Track all generated record rows for aggregation.

---

# Task 11: Aggregate and Plot Final Country-Level Results

- File: `workflow.py`
- Plot helper: `plot_country_sent_vs_payload(...)`
- Responsibilities:
  - Compute per-country average sent packets and decoded payloads.
  - Write:
    - `covered_countries_lrfhss_country_avg.csv`
  - Generate summary figure:
    - `sent_packets_vs_decoded_payload_country_avg.png`

---

# Task 12: Export Final Workflow Summary

- File: `workflow.py`
- Output: `workflow_summary.json`
- Responsibilities:
  - Record pipeline stages and runtime mode.
  - Store orbit metadata, coverage model, filtering results.
  - Include generated output file paths.
  - Provide one JSON artifact for reproducibility and audit.

---

# Data Flow Summary

- Inputs:
  - CLI args
  - Orbit/module references
  - LR-FHSS reference CSV
  - Country population coordinate dataset
- Transformations:
  - Orbit propagation -> coverage estimation -> feasible filtering -> stepwise decode mapping -> aggregation
- Outputs:
  - Trace CSVs
  - Per-country stepwise CSVs
  - Country average CSV
  - Plot PNG
  - Workflow JSON summary

---

# Notes on Reproducibility and Constraints

- Reproducibility:
  - `seed` combined with `step` and stable country hash.
- Constraint handling:
  - Options beyond current coverage are excluded before simulation.
- Reference-data bounded:
  - Decode estimates are derived from available demod rows in reference CSV.
- Graceful plotting:
  - Plot is skipped if `matplotlib` is unavailable.

---

# How to Regenerate Results

```powershell
python main.py \
  --nodes 0 2 7 15 40 90 180 260 400 700 1000 1500 \
  --demods 10 30 50 70 100 300 500 700 1000 \
  --scenario-steps 120 \
  --step-seconds 228.0
```

- Main summary output:
  - `results/lrfhss_communication/workflow_summary.json`

---

# End

- This deck documents the currently implemented rotation-stepwise LR-FHSS workflow.
- It can be extended with dedicated slides for power-policy and elevation-angle standalone studies.
