#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    integration_root = Path(__file__).resolve().parent
    snt_root = integration_root.parent

    parser = argparse.ArgumentParser(
        description=(
            "Replicate paper outputs with two methods: "
            "LR-FHSS communication curve and elevation-angle ECDF study."
        )
    )
    parser.add_argument(
        "--method",
        type=str,
        default="both",
        choices=["lrfhss", "elevation", "both"],
        help="Replication method to run.",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output-root", type=Path, default=integration_root / "results" / "paper_replication")

    parser.add_argument("--multi-beam-root", type=Path, default=snt_root / "Multi-Beam-LEO-Framework")
    parser.add_argument("--lrfhss-root", type=Path, default=snt_root / "lr-fhss_seq-families")

    parser.add_argument("--demods", type=int, default=100)
    parser.add_argument("--coding-rate", type=int, default=1)
    parser.add_argument("--metric", type=str, default="dec_payld")
    parser.add_argument("--drop-mode", type=str, default="rlydd", choices=["rlydd", "headerdrop", "hdrdd"])
    parser.add_argument("--packet-only", action="store_true")
    parser.add_argument("--node-min", type=float, default=100.0)
    parser.add_argument("--node-max", type=float, default=10000.0)
    parser.add_argument("--nodes", type=float, nargs="+", default=None)
    parser.add_argument("--x-min", type=float, default=None)
    parser.add_argument("--x-max", type=float, default=None)
    parser.add_argument("--y-max", type=float, default=None)
    parser.add_argument("--include-lifan", action="store_true")
    parser.add_argument("--include-infp", action="store_true")
    parser.add_argument("--export-pdf", action="store_true")

    parser.add_argument("--n-user", type=int, default=100000)
    return parser.parse_args()


def _ensure_reference_paths(multi_beam_root: Path, lrfhss_root: Path) -> None:
    if multi_beam_root.exists() and lrfhss_root.exists():
        return
    ensure_script = Path(__file__).resolve().parent / "ensure_reference_paths.py"
    subprocess.run(
        [
            sys.executable,
            str(ensure_script),
            "--multi-beam-root",
            str(multi_beam_root),
            "--lrfhss-root",
            str(lrfhss_root),
        ],
        check=True,
    )


def main() -> None:
    args = parse_args()
    method = str(args.method).lower()
    run_lrfhss = method in {"lrfhss", "both"}
    run_elevation = method in {"elevation", "both"}

    if run_lrfhss or run_elevation:
        _ensure_reference_paths(multi_beam_root=args.multi_beam_root, lrfhss_root=args.lrfhss_root)

    if run_lrfhss:
        from workflow_tasks.lrfhss_communication import run_reference_comparison

        lrfhss_output_dir = args.output_root / "lrfhss_compare"
        metric = "dec_pckts" if args.packet_only else args.metric
        drop_mode = "hdrdd" if args.drop_mode == "headerdrop" else args.drop_mode
        out_png, out_pdf = run_reference_comparison(
            reference_csv=None,
            output_dir=lrfhss_output_dir,
            lrfhss_root=args.lrfhss_root,
            demods=args.demods,
            coding_rate=args.coding_rate,
            metric=metric,
            drop_mode=drop_mode,
            y_max=args.y_max,
            x_min=args.x_min,
            x_max=args.x_max,
            include_lifan=args.include_lifan,
            include_infp=args.include_infp,
            node_min=args.node_min,
            node_max=args.node_max,
            selected_nodes=args.nodes,
            export_pdf=args.export_pdf,
        )
        print(f"[lrfhss] PNG: {out_png.resolve()}")
        generated_csv = lrfhss_output_dir / f"lrfhss_sim_cr{int(args.coding_rate)}.csv"
        print(f"[lrfhss] CSV: {generated_csv.resolve()}")
        if args.export_pdf:
            print(f"[lrfhss] PDF: {out_pdf.resolve()}")

    if run_elevation:
        from workflow_tasks.elevation_angle import run_elevation_angle_study

        elevation_output_dir = args.output_root / "elevation_angle"
        summary = run_elevation_angle_study(
            multi_beam_root=args.multi_beam_root,
            output_dir=elevation_output_dir,
            seed=args.seed,
            n_user=args.n_user,
        )
        print(f"[elevation] Plot: {summary['plot']}")
        print(f"[elevation] CSV:  {summary['metrics_csv']}")


if __name__ == "__main__":
    main()
