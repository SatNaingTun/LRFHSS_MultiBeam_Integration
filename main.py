import argparse
import subprocess
import sys
from pathlib import Path


def parse_args():
    integration_root = Path(__file__).resolve().parent
    snt_root = integration_root.parent

    parser = argparse.ArgumentParser(
        description=(
            "Run workflow (rotation scope only): orbit rotation -> coverage at satellite location -> "
            "check nodes/demods -> LR-FHSS decode payload/collision analysis -> per-country CSV/plots -> summary"
        )
    )
    parser.add_argument("--multi-beam-root", type=Path, default=snt_root / "Multi-Beam-LEO-Framework")
    parser.add_argument("--lrfhss-root", type=Path, default=snt_root / "lr-fhss_seq-families")
    parser.add_argument(
        "--reference-csv",
        type=Path,
        default=snt_root / "lr-fhss_seq-families" / "headerResults" / "data-25dc-cr1.csv",
    )
    parser.add_argument("--output-dir", type=Path, default=integration_root / "results" / "lrfhss_communication")
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
    parser.add_argument("--scenario-steps", type=int, default=120)
    parser.add_argument("--step-seconds", type=float, default=228.0)
    parser.add_argument("--runs-per-point", type=int, default=10)
    parser.add_argument("--baseline-circuit-power-w", type=float, default=35.0)
    parser.add_argument("--per-idle-demodulator-power-w", type=float, default=0.12)
    parser.add_argument("--per-busy-demodulator-power-w", type=float, default=0.80)
    parser.add_argument("--demod-tx-capacity-per-step", type=float, default=250.0)
    parser.add_argument(
        "--elevation-user-cap",
        type=int,
        default=5000,
        help="Max users used in rotation-based elevation SNR/SINR stage (smaller = faster).",
    )
    parser.add_argument(
        "--elevation-steps-per-angle",
        type=int,
        default=1,
        help="How many rotation steps to sample per target elevation angle (25/55/90).",
    )
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
        reference_csv=args.reference_csv,
        scenario_steps=args.scenario_steps,
        step_seconds=args.step_seconds,
        runs_per_point=args.runs_per_point,
        baseline_circuit_power_w=args.baseline_circuit_power_w,
        per_idle_demodulator_power_w=args.per_idle_demodulator_power_w,
        per_busy_demodulator_power_w=args.per_busy_demodulator_power_w,
        demod_tx_capacity_per_step=args.demod_tx_capacity_per_step,
        elevation_user_cap=args.elevation_user_cap,
        elevation_steps_per_angle=args.elevation_steps_per_angle,
    )


if __name__ == "__main__":
    main()
