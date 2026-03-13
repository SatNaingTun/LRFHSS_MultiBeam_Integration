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

## Outputs
- `results/heavy_load/heavy_load_metrics.json`
- `results/heavy_load/heavy_load_metrics.csv`
- `results/heavy_load/heavy_load_demodulator_constraints.png`
- `results/heavy_load/workflow_summary.json`
