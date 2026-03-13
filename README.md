# LRFHSS_MultiBeam_Integration

Primary pipeline is now:

START
- Initialize simulation parameters
- Compute satellite orbit
- Generate visibility windows
- Generate IoT nodes
- Assign LR-FHSS packets
- Check satellite visibility
- Select satellite power mode
- Transmit fragments
- Detect collisions
- Allocate demodulators
- Baseline packet decoding
- Store metrics
- Generate performance plots
END

Power mode logic:

```python
def power_mode(nodes):
    if nodes == 0:
        return "sleep"
    elif nodes < 200:
        return "idle"
    else:
        return "busy"
```

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
python run_integration.py --help
```

## Outputs
- `results/heavy_load/heavy_load_metrics.json`
- `results/heavy_load/heavy_load_metrics.csv`
- `results/heavy_load/heavy_load_demodulator_constraints.png`
- `results/heavy_load/workflow_summary.json`
