# LRFHSS_MultiBeam_Integration

This README only covers:
1. `main.py`
2. `one_pos_lrfhss_sim.py`
3. `modules/satellite_stepper.py`
4. `one_location.py`
5. `fixed_nodes_one_pos_lrfhss_sim.py` (fixed-position flow)

## 1) `main.py`
`main.py` is a launcher that runs `modules/satellite_simulator.py` main flow.

Run:
```powershell
python .\main.py --steps 5
```

Useful parameters (forwarded to satellite simulator):
- `--steps`
- `--include-elev on|off`
- `--infp on|off`
- `--inf-demods`
- `--elev-list 90 79 55 25`
- `--coding-rate`
- `--drop-mode`
- `--runs-per-node`
- `--output-dir`
- `--one_pos_output_dir`

Example:
```powershell
python .\main.py --steps 5 --include-elev on --infp on --elev-list 90 79 55 25
```

## 2) `one_pos_lrfhss_sim.py`
Runs one-position LR-FHSS simulation and optional per-elevation outputs.

Run:
```powershell
python .\one_pos_lrfhss_sim.py
```

Useful parameters:
- `--step` (read a specific step from stepper CSV)
- `--sat-lat`, `--sat-lon`
- `--infp on|off` (default: `off`)
- `--inf-demods`
- `--include-lifan`
- `--elev-list`
- `--coding-rate`, `--drop-mode`, `--metric`
- `--node-min`, `--node-max`
- `--x-min`, `--x-max`, `--y-min`, `--y-max`

Examples:
```powershell
python .\one_pos_lrfhss_sim.py --infp on
python .\one_pos_lrfhss_sim.py --step 0 --infp off --elev-list 90 79 55 25
```

## 3) `modules/satellite_stepper.py`
Generates step-wise satellite geometry/coverage and per-elevation state outputs.

Run:
```powershell
python .\modules\satellite_stepper.py
```

Useful parameters:
- `--output-csv`
- `--current-pos-json`
- `--population-csv`, `--ocean-csv`
- `--node-population-ratio`, `--demd-population-ratio`
- `--minimum-frames`
- `--elev-list`
- `--demod-activity-ratio`, `--demod-sleep-ratio`
- `--baseline-power-w`, `--idle-demodulator-power-w`, `--busy-demodulator-power-w`

Example:
```powershell
python .\modules\satellite_stepper.py --minimum-frames 720 --elev-list 90 79 55 25
```

## 4) `one_location.py`
Convenience launcher for one-location runs using satellite simulator defaults:
- `--steps 1`
- `--infp on`
- `--include-elev on`

Run:
```powershell
python .\one_location.py
```

Override defaults if needed:
```powershell
python .\one_location.py --steps 2
python .\one_location.py --include-elev off
python .\one_location.py --infp off
```

## 5) `fixed_nodes_one_pos_lrfhss_sim.py` (fixed-position flow)
Runs one-position LR-FHSS simulation with fixed node counts (dense/sparse profiles).

Run:
```powershell
python .\fixed_nodes_one_pos_lrfhss_sim.py
```

Profiles:
- dense (default): fixed nodes = `10000`
- sparse: fixed nodes = `100`

Useful parameters:
- `--profile dense|sparse`
- `--given-nodes` (override profile default)
- `--infp on|off`
- `--inf-demods`
- `--elev-list`
- `--coding-rate`, `--drop-mode`, `--metric`

Examples:
```powershell
python .\fixed_nodes_one_pos_lrfhss_sim.py
python .\fixed_nodes_one_pos_lrfhss_sim.py --profile sparse
python .\fixed_nodes_one_pos_lrfhss_sim.py --given-nodes 1000 --infp on
```

## Parameter Usage Differences
- `main.py`:
  - Best for multi-step full pipeline.
  - Uses satellite simulator allocation flow and plotting pipeline.
- `one_pos_lrfhss_sim.py`:
  - Best for one-position analysis and quick LR-FHSS curve generation.
  - Direct control of INFP via `--infp on|off`.
- `modules/satellite_stepper.py`:
  - Best for geometry/coverage/elevation-state generation.
  - Does not run LR-FHSS decode plotting by itself.
- `one_location.py`:
  - Best for quick one-location execution with opinionated defaults.
  - Defaults to `steps=1`, `infp=on`, `include-elev=on`.
- `fixed_nodes_one_pos_lrfhss_sim.py`:
  - Best for fixed-position/fixed-node sweeps using dense/sparse presets.
  - Supports explicit fixed-node override via `--given-nodes`.
