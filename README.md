# LRFHSS_MultiBeam_Integration

Primary pipeline is now:

START
- Initialize simulation parameters
- Compute satellite orbit
- Generate visibility windows
- Generate IoT nodes
- Assign LR-FHSS packets
- Check satellite visibility
- Transmit fragments
- Detect collisions
- Allocate demodulators
- Baseline packet decoding
- Store metrics
- Generate performance plots
END

Power model notes:
- Power consumption uses allocated demods and demod utilization.
- Power plots are grouped by `policy` and `allocated_demods`.
- Refined equation: `P_total = P_circuit + N_idle*P_idle + N_busy*P_busy`.
- Two policies are compared: `EnergyAware` and `NonEnergyAware`.
- Monte Carlo statistics use `--runs-per-point` (default `50`) with variance and 95% confidence intervals.

## Run
```powershell
python run_integration.py
```

If `Multi-Beam-LEO-Framework` or `lr-fhss_seq-families` does not exist in the SNT parent folder, `run_integration.py`
automatically runs `ensure_reference_paths.py` to download/extract or clone them.

## Sample Commands
```powershell
python run_integration.py --nodes 0 2 7 15 40 90 180 260 400 700 1000 1500 --demods 10 30 50 70 100 300 500 700 1000
```

```powershell
python run_integration.py --runs-per-point 50 --scenario-steps 120
```

```powershell
python run_integration.py --help
```

## Outputs
- `results/heavy_load/heavy_load_metrics.json`
- `results/heavy_load/heavy_load_metrics.csv`
- `results/heavy_load/heavy_load_demodulator_constraints.png`
- `results/heavy_load/heavy_load_demodulator_constraints_header_payload.png`
- `results/heavy_load/power_consumption_by_demods.png`
- `results/heavy_load/throughput_bps.png`
- `results/heavy_load/energy_per_decoded_bit.png`
- `results/heavy_load/decoding_efficiency.png`
- `results/heavy_load/workflow_summary.json`

## LR-FHSS Compare Plot
Use `lrfhss_communication.py` for paper-style comparison output in `results/lrfhss_compare` with name
`lrfhss_demod_<demods>.png`.

Recommended `ymax`:
- `100` demodulators: `--y-max 600`
- `1000` demodulators: `--y-max 2600`

Plot window is not fixed by default (auto-scale). If needed, set explicit X limits with
`--x-min` and `--x-max`.

Examples:
```powershell
python lrfhss_communication.py --demods 100 --y-max 600
python lrfhss_communication.py --demods 1000 --y-max 2600
python lrfhss_communication.py --demods 100 --x-min 100 --x-max 10000
```
