from __future__ import annotations

import argparse
import csv
import json

from pathlib import Path

from modules.satellite_stepper import SatelliteStepper
from ProjectConfig import node_population_ratio


def _select_available_demod(requested_demod: int, available_demods: list[int]) -> int:
    eligible = [d for d in available_demods if d <= int(requested_demod)]
    if eligible:
        return int(max(eligible))
    if available_demods:
        return int(min(available_demods))
    return int(max(1, requested_demod))


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(
        description=(
            "One-position pipeline: run SatelliteStepper output, get current nodes/demods, "
            "then run LR-FHSS communication comparison in a dedicated output folder."
        )
    )

    parser.add_argument("--output-dir", type=Path, default=root / "results" / "one_pos_lrfhss")

    # Satellite stepper stage (same style outputs as satellite_stepper main)
    parser.add_argument("--sat-lat", type=float, default=None, help="Optional override for satellite latitude (deg).")
    parser.add_argument("--sat-lon", type=float, default=None, help="Optional override for satellite longitude (deg).")
    parser.add_argument(
        "--stepper-output-csv",
        type=Path,
        default=None,
        help="Satellite stepper CSV path. Default: <output-dir>/satellite_steps.csv",
    )
    parser.add_argument(
        "--stepper-current-json",
        type=Path,
        default=None,
        help="Satellite stepper current JSON path. Default: <output-dir>/satellite_steps_current_pos.json",
    )
    
    parser.add_argument("--population-csv", type=Path, default=root / "Data" / "csv" / "population_data.csv")
    parser.add_argument("--ocean-csv", type=Path, default=root / "Data" / "csv" / "ocean_data.csv")
    parser.add_argument("--node-population-ratio", type=float, default=node_population_ratio)
    parser.add_argument("--nodes-per-demodulator", type=int, default=250)
    parser.add_argument("--minimum-frames", type=int, default=720)

    # LR-FHSS communication stage (same shape as lrfhss_communication main)
    parser.add_argument("--lrfhss-root", type=Path, default=root / "LRFHSS")
    parser.add_argument("--reference-csv", type=Path, default=None)
    parser.add_argument("--use-existing-csv", action="store_true")
    parser.add_argument("--generated-csv", type=Path, default=None)
    parser.add_argument(
        "--node-points",
        type=int,
        default=None,
        help="Number of node sweep points. Default: sim_nodes value from current stepper position.",
    )
    parser.add_argument("--node-min", type=float, default=None)
    parser.add_argument("--node-max", type=float, default=None)
    parser.add_argument("--runs-per-node", type=int, default=1)
    parser.add_argument("--inf-demods", type=int, default=None)
    parser.add_argument("--coding-rate", type=int, default=1)
    parser.add_argument("--metric", type=str, default="dec_payld")
    parser.add_argument("--drop-mode", type=str, default="rlydd", choices=["rlydd", "hdrdd", "headerdrop"])
    parser.add_argument("--x-min", type=float, default=None)
    parser.add_argument("--x-max", type=float, default=None)
    parser.add_argument("--y-max", type=float, default=None)
    parser.add_argument("--include-lifan", action="store_true")
    parser.add_argument("--include-infp", action="store_true")
    parser.add_argument("--export-pdf", action="store_true")
    parser.add_argument("--link-budget-log", action=argparse.BooleanOptionalAction, default=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    # Delay heavy import so --help remains lightweight.
    try:
        from workflow_tasks.lrfhss_communication import (
            list_available_demod_counts,
            run_reference_comparison,
        )
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "Missing dependency while importing lrfhss_communication. "
            "Install required LR-FHSS deps (for example: pip install galois)."
        ) from exc

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    stepper_csv = args.stepper_output_csv or (output_dir / "satellite_steps.csv")
    stepper_json = args.stepper_current_json or (output_dir / "satellite_steps_current_pos.json")

    stepper = SatelliteStepper(
        output_csv_path=stepper_csv,
        population_csv_path=args.population_csv,
        ocean_csv_path=args.ocean_csv,
        current_pos_json_path=stepper_json,
        node_penetration_ratio=args.node_penetration_ratio,
        nodes_per_demodulator=args.nodes_per_demodulator,
        minimum_frames=args.minimum_frames,
    )

    stepper.current()

    pos = stepper.get_pos()
    sat_lat = float(pos["latitude_deg"] if args.sat_lat is None else args.sat_lat)
    sat_lon = float(pos["longitude_deg"] if args.sat_lon is None else args.sat_lon)

    # If user passed explicit lat/lon, estimate coverage for that location.
    if args.sat_lat is not None or args.sat_lon is not None:
        est = stepper.estimate_row_for_lat_lon(sat_lat_deg=sat_lat, sat_lon_deg=sat_lon)
        requested_nodes = int(est["calculated_nodes"])
        requested_demods = int(est["calculated_demodulators"])
    else:
        # Directly from persisted current CSV row as requested.
        requested_nodes = int(stepper.get_current_nodes())
        requested_demods = int(stepper.get_current_demodulators())
    print(requested_nodes, requested_demods)
    sim_nodes = max(1, requested_nodes)
    sim_demods = max(1, requested_demods)
    drop_mode = "hdrdd" if args.drop_mode == "headerdrop" else args.drop_mode

    chosen_demods = int(sim_demods)
    if args.use_existing_csv:
        if args.reference_csv is None:
            raise ValueError("--reference-csv is required with --use-existing-csv.")
        available_demods = list_available_demod_counts(
            reference_csv=args.reference_csv,
            coding_rate=int(args.coding_rate),
            family="driver",
        )
        chosen_demods = _select_available_demod(requested_demod=sim_demods, available_demods=available_demods)

    generated_csv = args.generated_csv or (output_dir / f"lrfhss_sim_cr{int(args.coding_rate)}_one_pos.csv")
    effective_node_points = int(sim_nodes if args.node_points is None else args.node_points)
    out_png, out_pdf = run_reference_comparison(
        reference_csv=args.reference_csv,
        output_dir=output_dir,
        lrfhss_root=args.lrfhss_root,
        generate_csv_from_simulation=not args.use_existing_csv,
        generated_csv=generated_csv,
        sim_node_points=max(1, int(effective_node_points)),
        runs_per_node=max(1, int(args.runs_per_node)),
        inf_demods=args.inf_demods,
        demods=int(chosen_demods),
        coding_rate=int(args.coding_rate),
        metric=str(args.metric),
        drop_mode=drop_mode,
        y_max=args.y_max,
        x_min=args.x_min,
        x_max=args.x_max,
        include_lifan=bool(args.include_lifan),
        include_infp=bool(args.include_infp),
        node_min=args.node_min,
        node_max=args.node_max,
        selected_nodes=None,
        export_pdf=bool(args.export_pdf),
        output_tag="one_pos",
        link_budget_log=bool(args.link_budget_log),
    )

    summary = {
        "sat_lat_deg": float(sat_lat),
        "sat_lon_deg": float(sat_lon),
        "requested_nodes": int(requested_nodes),
        "requested_demodulators": int(requested_demods),
        "sim_nodes": int(sim_nodes),
        "sim_demodulators": int(chosen_demods),
        "drop_mode": str(drop_mode),
        "node_points": int(effective_node_points),
        "node_min": float(args.node_min) if args.node_min is not None else None,
        "node_max": float(args.node_max) if args.node_max is not None else None,
        "stepper_csv": str(Path(stepper_csv).resolve()),
        "stepper_current_json": str(Path(stepper_json).resolve()),
        "lrfhss_plot_png": str(Path(out_png).resolve()),
        "lrfhss_plot_pdf": str(Path(out_pdf).resolve()) if bool(args.export_pdf) else None,
        "generated_csv": str(Path(generated_csv).resolve()) if not args.use_existing_csv else None,
    }

    summary_json = output_dir / "one_pos_summary.json"
    with summary_json.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    summary_csv = output_dir / "one_pos_summary.csv"
    with summary_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(summary.keys()))
        writer.writeheader()
        writer.writerow(summary)

    print(
        f"one_pos_done lat={summary['sat_lat_deg']:.6f} lon={summary['sat_lon_deg']:.6f} "
        f"nodes={summary['sim_nodes']} demods={summary['sim_demodulators']}"
    )
    print(f"stepper_csv={summary['stepper_csv']}")
    print(f"lrfhss_plot_png={summary['lrfhss_plot_png']}")
    print(f"summary_json={summary_json.resolve()}")
    print(f"summary_csv={summary_csv.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
