import argparse
from pathlib import Path

from workflow import run_workflow


def parse_args():
    integration_root = Path(__file__).resolve().parent
    snt_root = integration_root.parent

    parser = argparse.ArgumentParser(
        description=(
            "Run full workflow: orbit -> visibility -> nodes -> LR-FHSS packets -> visibility check -> "
            "power mode -> transmit -> collisions -> demods -> baseline decode -> metrics -> plots"
        )
    )
    parser.add_argument("--multi-beam-root", type=Path, default=snt_root / "Multi-Beam-LEO-Framework")
    parser.add_argument("--lrfhss-root", type=Path, default=snt_root / "LR-FHSS_LEO")
    parser.add_argument("--output-dir", type=Path, default=integration_root / "results" / "heavy_load")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--node-min", type=int, default=10)
    parser.add_argument("--node-max", type=int, default=1500)
    parser.add_argument("--node-points", type=int, default=14)
    parser.add_argument(
        "--nodes",
        type=int,
        nargs="+",
        default=[0, 1, 5, 10, 20, 50, 100, 150, 200, 300, 500, 800, 1000, 1200, 1500],
        help="Explicit node list; overrides --node-min/--node-max/--node-points.",
    )
    parser.add_argument("--demods", type=int, nargs="+", default=[10, 100, 1000])
    return parser.parse_args()


def main():
    args = parse_args()
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
    )


if __name__ == "__main__":
    main()
