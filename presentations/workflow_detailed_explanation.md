---
marp: true
---


# Detailed Workflow Explanation

## 1) What this workflow does
The workflow evaluates LR-FHSS uplink performance for many traffic loads and demodulator capacities. It combines satellite visibility constraints with decoding behavior and produces machine-readable metrics plus plots.

Main execution path:
- `run_integration.py` parses CLI arguments and ensures external repositories are available.
- `workflow.py` executes the simulation pipeline and writes artifacts under `results/heavy_load/`.

---

## 2) Entry point and orchestration
`run_integration.py`:
- Defines defaults for:
  - Multi-beam framework path
  - LR-FHSS framework path
  - Output directory
  - Seed
  - Node list and demod list
- If external repos are missing, it runs `ensure_reference_paths.py`.
- Calls `workflow.run_workflow(...)` with all parameters.

Why this matters:
- You can run quickly with defaults.
- You can also override specific parameters without editing code.

---

## 3) Pipeline stages in `workflow.py`

### Stage A - Initialize simulation parameters
Function: `initialize_simulation_parameters(...)`
- Builds a `PipelineConfig` dataclass:
  - `node_loads`
  - `demodulator_options`
  - `runs_per_point`
  - visibility threshold
  - output path
  - seed
- If `nodes_list` is provided, it uses that list directly.
- Otherwise it generates log-spaced node loads from min/max/points.

---

### Stage B - Load external simulation components
Function call: `bootstrap(multi_beam_root, lrfhss_root)`
- Loads geometry utilities and `LoRaNetwork` implementation from external repos.
- This keeps this repository focused on integration flow rather than reimplementing the underlying PHY/network internals.
---

### Stage C - Compute orbit and visibility
Functions:
- `compute_satellite_orbit(network_geometry)`
- `generate_visibility_windows(sat_pos, utils_mod, min_elev_deg)`

Details:
- Satellite position is obtained from the geometry module.
- Elevation angle is converted to degrees.
- A boolean visibility mask is built using threshold `>= 10 deg`.
- Continuous visible intervals are extracted as `(start_frame, end_frame)` tuples.
---

### Stage D - Per-load traffic generation
Functions:
- `generate_iot_nodes(node_count)`
- `assign_lrfhss_packets(nodes)`
- `check_satellite_visibility(visibility_info)`
- `select_satellite_power_mode(nodes)`
- `transmit_fragments(packet_count, visible)`
---

Details:
- IoT nodes are represented as IDs `[0..N-1]`.
- One packet per node is assigned in this baseline workflow.
- A representative frame is chosen from the first visibility window.
- Power mode logic:
  - `sleep` for `0` nodes
  - `idle` for `1..199`
  - `busy` for `>=200`
- If satellite not visible at selected frame, transmitted count is forced to `0`.
---

### Stage E - Demodulator allocation and decode
Functions:
- `allocate_demodulators(requested_demods, mode)`
- `baseline_packet_decoding(...)`
- `detect_collisions(decoded_metrics)`
---

Details:
- In `sleep`, allocated demodulators are set to `0`.
- Otherwise allocation equals requested value.
- `baseline_packet_decoding` constructs `LoRaNetwork(...)`, runs simulation, and collects:
  - `tracked_txs`
  - `decoded_payloads`
  - `decoded_bytes`
  - `collided`
- For zero-load or zero-demod cases, it returns zeros without running network simulation.

---
### Stage F - Persist metrics and plots
Functions:
- `store_metrics(records, output_dir)`
- `generate_performance_plots(records, output_dir)`

Outputs:
- JSON + CSV metrics
- Plot with all series
- Plot split by power mode
- `workflow_summary.json` with workflow steps, power mode logic, output paths, and visibility windows
---

## 4) Data schema (record-level)
Each row in `heavy_load_metrics.csv` includes:
- `nodes`
- `power_mode`
- `visible`
- `selected_frame`
- `requested_demods`
- `allocated_demods`
- `mode_label`
- `decoded_payloads`
- `tracked_txs`
- `decoded_bytes`
- `collided`

This schema is enough to reproduce most performance analyses without rerunning simulation.
---

## 5) Interpreting the current result set
From `results/heavy_load/heavy_load_metrics.csv` currently in the repo:
- Total rows: `108`
- Node range present: `0` to `1500`
- Demod levels present: `10, 30, 50, 70, 100, 300, 500, 700, 1000`
- Modes present: `sleep`, `idle`, `busy`

Observed behavior:
- Decoded payload increases with demod count at lower loads.
- Under high load, collisions rise and decoded payload can collapse, even with high demod counts.
- The maximum demod count is not always the best operating point for each node load in this baseline setup.
---

## 6) Why performance drops at heavy load
Likely combined causes:
- Contention growth: more overlapping transmissions with larger node populations
- Header/payload collisions: demodulator count helps concurrency but does not eliminate channel overlap
- Saturation effects in baseline decode path under aggressive load

This is consistent with seeing near-zero decoded payload at very high node loads.
---

## 7) How to present this workflow clearly
Suggested narrative:
1. Problem and objective
2. System model and assumptions
3. End-to-end workflow diagram
4. Parameter sweep design (nodes x demods)
5. Result plots and interpretation
6. Bottlenecks and next optimization targets
---

## 8) Recommended next technical improvements
- Increase `runs_per_point` and report confidence intervals
- Re-enable side-by-side comparison of `Baseline` vs `Early` decode/drop
- Add normalization metrics:
  - decode success ratio (`decoded_payloads / tracked_txs`)
  - collision ratio (`collided / tracked_txs`)
- Add auto-generated experiment manifest (CLI args + git commit hash) for strict reproducibility
