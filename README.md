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
- `--onboard-demods` sets fixed satellite hardware demod capacity; coverage affects load, not total demod hardware.
- Two policies are compared: `EnergyAware` and `NonEnergyAware`.
- Monte Carlo statistics use `--runs-per-point` (default `50`) with variance and 95% confidence intervals.

## Run
```powershell
python main.py
```

If `Multi-Beam-LEO-Framework` or `lr-fhss_seq-families` does not exist in the SNT parent folder, `main.py`
automatically runs `ensure_reference_paths.py` to download/extract or clone them.

## Sample Commands
```powershell
python main.py --nodes 0 2 7 15 40 90 180 260 400 700 1000 1500 --demods 10 30 50 70 100 300 500 700 1000
python main.py --onboard-demods 512 --demods 10 30 50 70 100 300 500
```

```powershell
python main.py --runs-per-point 50 --scenario-steps 120
```

```powershell
python main.py --help
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
Use `workflow_tasks/lrfhss_communication.py` for paper-style comparison output in `results/lrfhss_compare` with name
`lrfhss_demod_<demods>.png`.

Recommended `ymax`:
- `100` demodulators: `--y-max 600`
- `1000` demodulators: `--y-max 2600`

Plot window is not fixed by default (auto-scale). If needed, set explicit X limits with
`--x-min` and `--x-max`.

Examples:
```powershell
python workflow_tasks/lrfhss_communication.py --demods 100 --y-max 600
python workflow_tasks/lrfhss_communication.py --demods 1000 --y-max 2600
python workflow_tasks/lrfhss_communication.py --demods 100 --x-min 100 --x-max 10000
python workflow_tasks/lrfhss_communication.py --demods 1000 --include-infp
python workflow_tasks/lrfhss_communication.py --demods 100 --packet-only
python workflow_tasks/lrfhss_communication.py --demods 100 --drop-mode headerdrop
python workflow_tasks/lrfhss_communication.py --paper-cr1-figure 8a
python workflow_tasks/lrfhss_communication.py --paper-cr1-figure 9a
python workflow_tasks/lrfhss_communication.py --paper-cr1-figure both
```

Notes:
- Simulation CSV generation now uses local `LRFHSS/LRFHSS_simulator.py` (no external repo copy needed).
- Default simulator values are read from `LRFHSS/base/base.py`.

## Paper Replication (Two Methods)
Use `replicate_paper.py` to run either or both replication methods:

```powershell
python replicate_paper.py --method lrfhss --demods 100 --y-max 600
python replicate_paper.py --method lrfhss --demods 1000 --y-max 2600
python replicate_paper.py --method elevation --n-user 100000
python replicate_paper.py --method both --demods 100 --y-max 600 --n-user 100000
```
