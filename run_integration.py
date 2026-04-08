import argparse
import subprocess
import sys
from pathlib import Path


def parse_args():
    integration_root = Path(__file__).resolve().parent
    snt_root = integration_root.parent

    parser = argparse.ArgumentParser(
        description=(
            "Run full workflow: orbit -> visibility -> nodes -> LR-FHSS packets -> visibility check -> "
            "demod allocation -> transmit -> collisions -> demods -> baseline decode -> metrics -> plots"
        )
    )
    parser.add_argument("--multi-beam-root", type=Path, default=snt_root / "Multi-Beam-LEO-Framework")
    parser.add_argument("--lrfhss-root", type=Path, default=snt_root / "lr-fhss_seq-families")
    parser.add_argument("--output-dir", type=Path, default=integration_root / "results" / "heavy_load")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--node-min", type=int, default=10)
    parser.add_argument("--node-max", type=int, default=1500)
    parser.add_argument("--node-points", type=int, default=14)
    parser.add_argument(
        "--nodes",
        type=int,
        nargs="+",
        default=[0, 2, 7, 15, 40, 90, 180, 260, 400, 700, 1000, 1500],
        help="Explicit node list; overrides --node-min/--node-max/--node-points.",
    )
    parser.add_argument("--demods", type=int, nargs="+", default=[10, 30, 50, 70, 100, 300, 500, 700, 1000])
    parser.add_argument("--no-csv", action="store_true", help="Skip CSV export.")
    parser.add_argument("--no-plots", action="store_true", help="Skip plot generation.")
    parser.add_argument("--battery-initial-percent", type=float, default=100.0)
    parser.add_argument("--battery-decay-per-w", type=float, default=0.04)
    parser.add_argument("--charging-rate-per-step", type=float, default=8.0)
    parser.add_argument("--low-battery-threshold", type=float, default=5.0)
    parser.add_argument("--idle-battery-threshold", type=float, default=30.0)
    parser.add_argument("--high-charge-threshold", type=float, default=100.0)
    parser.add_argument("--runs-per-point", type=int, default=50)
    parser.add_argument("--scenario-steps", type=int, default=120)
    parser.add_argument("--step-seconds", type=float, default=228.0)
    parser.add_argument("--panel-area-m2", type=float, default=0.40)
    parser.add_argument("--solar-irradiance-w-m2", type=float, default=950.0)
    parser.add_argument("--panel-efficiency", type=float, default=0.20)
    parser.add_argument("--power-conditioning-efficiency", type=float, default=0.90)
    parser.add_argument("--battery-capacity-wh", type=float, default=220.0)
    parser.add_argument("--battery-max-charge-w", type=float, default=80.0)
    parser.add_argument("--battery-charge-efficiency", type=float, default=0.95)
    parser.add_argument("--battery-discharge-efficiency", type=float, default=0.95)
    parser.add_argument("--demod-tx-capacity-per-step", type=float, default=8.0)
    parser.add_argument("--base-power-w", type=float, default=5.0)
    parser.add_argument("--rf-frontend-power-w", type=float, default=1.8)
    parser.add_argument("--min-demod-allocation", type=int, default=5)
    parser.add_argument("--max-demod-step-change", type=int, default=80)
    return parser.parse_args()


def main():
    args = parse_args()

    from workflow import run_workflow

    if (not args.multi_beam_root.exists()) or (not args.lrfhss_root.exists()):
        ensure_script = Path(__file__).resolve().parent / "ensure_reference_paths.py"
        subprocess.run(
            [
                sys.executable,
                str(ensure_script),
                "--multi-beam-root",
                str(args.multi_beam_root),
                "--lrfhss-root",
                str(args.lrfhss_root),
            ],
            check=True,
        )

    run_workflow(
        multi_beam_root=args.multi_beam_root,
        lrfhss_root=args.lrfhss_root,
        output_dir=args.output_dir,
        seed=args.seed,
        node_min=args.node_min,
        node_max=args.node_max,
        node_points=args.node_points,
        demodulator_options=args.demods,
        nodes_list=args.nodes,
        export_csv=not args.no_csv,
        generate_plots=not args.no_plots,
        battery_initial_percent=args.battery_initial_percent,
        battery_decay_per_w=args.battery_decay_per_w,
        charging_rate_per_step=args.charging_rate_per_step,
        low_battery_threshold=args.low_battery_threshold,
        idle_battery_threshold=args.idle_battery_threshold,
        high_charge_threshold=args.high_charge_threshold,
        runs_per_point=args.runs_per_point,
        scenario_steps=args.scenario_steps,
        step_seconds=args.step_seconds,
        panel_area_m2=args.panel_area_m2,
        solar_irradiance_w_m2=args.solar_irradiance_w_m2,
        panel_efficiency=args.panel_efficiency,
        power_conditioning_efficiency=args.power_conditioning_efficiency,
        battery_capacity_wh=args.battery_capacity_wh,
        battery_max_charge_w=args.battery_max_charge_w,
        battery_charge_efficiency=args.battery_charge_efficiency,
        battery_discharge_efficiency=args.battery_discharge_efficiency,
        demod_tx_capacity_per_step=args.demod_tx_capacity_per_step,
        base_power_w=args.base_power_w,
        rf_frontend_power_w=args.rf_frontend_power_w,
        min_demod_allocation=args.min_demod_allocation,
        max_demod_step_change=args.max_demod_step_change,
    )


if __name__ == "__main__":
    main()
