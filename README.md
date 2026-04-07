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
- Net power is computed from solar generation minus platform consumption.
- Battery update is energy-based and uses `net_power_watts` per simulation step.
- Power and net-power plots are grouped by `policy` and `allocated_demods`.
- Refined equation: `P_total = P_base + P_RF + D * P_demod(rho)`.
- Solar model: `P_gen = A_panel * G_sun * eta_panel` with eclipse windows.
- Two policies are compared: `EnergyAware` (battery-aware demod scaling) and `NonEnergyAware`.
- Monte Carlo statistics use `--runs-per-point` (default `50`) with variance and 95% confidence intervals.

## Run
```powershell
python run_integration.py
```

If `Multi-Beam-LEO-Framework` or `LR-FHSS_LEO` does not exist in the SNT parent folder, `run_integration.py`
automatically runs `ensure_reference_paths.py` to download/extract or clone them.

## Sample Commands
```powershell
python run_integration.py --nodes 0 2 7 15 40 90 180 260 400 700 1000 1500 --demods 10 30 50 70 100 300 500 700 1000
```

```powershell
python run_integration.py --runs-per-point 50 --scenario-steps 120 --battery-capacity-wh 220 --panel-area-m2 0.40
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
- `results/heavy_load/battery_percentage_over_load.png`
- `results/heavy_load/net_power_by_demods.png`
- `results/heavy_load/throughput_bps.png`
- `results/heavy_load/energy_per_decoded_bit.png`
- `results/heavy_load/decoding_efficiency.png`
- `results/heavy_load/workflow_summary.json`
