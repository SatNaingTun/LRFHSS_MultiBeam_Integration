from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys
from typing import Any

from modules.satellite_stepper import SatelliteStepper
from ProjectConfig import node_population_ratio, demd_population_ratio, elev_list
from LRFHSS import LRFHSS_simulator as sim

def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(
        description=(
            "One-position LR-FHSS run: get current nodes/demods from SatelliteStepper, "
            "then run LRFHSS_simulator.runsim2plot directly."
        )
    )
    parser.add_argument("--output-dir", type=Path, default=root / "results" / "one_pos_lrfhss")
    parser.add_argument("--sat-lat", type=float, default=None, help="Optional override latitude for node/demod estimate.")
    parser.add_argument("--sat-lon", type=float, default=None, help="Optional override longitude for node/demod estimate.")
    parser.add_argument(
        "--stepper-output-csv",
        type=Path,
        default=root / "results" / "one_pos_lrfhss" / "satellite_steps.csv",
        help="Satellite stepper CSV to use as source of calculated_nodes/calculated_demodulators.",
    )
    parser.add_argument(
        "--stepper-current-json",
        type=Path,
        default=None,
        help="Default: <output-dir>/satellite_steps_current_pos.json",
    )
    parser.add_argument("--population-csv", type=Path, default=root / "Data" / "csv" / "population_data.csv")
    parser.add_argument("--ocean-csv", type=Path, default=root / "Data" / "csv" / "ocean_data.csv")
    parser.add_argument("--node-population-ratio", type=float, default=float(node_population_ratio))
    parser.add_argument("--demd-population-ratio", type=float, default=float(demd_population_ratio))
    parser.add_argument("--minimum-frames", type=int, default=720)
    parser.add_argument("--elev-list", type=list, default=elev_list, help="List of elevations to simulate (degrees).")

    parser.add_argument("--lrfhss-root", type=Path, default=root / "LRFHSS")
    parser.add_argument("--coding-rate", type=int, default=1)
    parser.add_argument("--metric", type=str, default="dec_payld")
    parser.add_argument("--drop-mode", type=str, default="rlydd", choices=["rlydd", "hdrdd", "headerdrop"])
    parser.add_argument("--runs-per-node", type=int, default=1)
    parser.add_argument("--include-lifan", action="store_true")
    parser.add_argument("--include-infp", action="store_true")
    parser.add_argument("--inf-demods", type=int, default=None)
    parser.add_argument("--node-min", type=float, default=None)
    parser.add_argument("--node-max", type=float, default=10000.0)
    parser.add_argument("--x-min", type=float, default=100)
    parser.add_argument("--x-max", type=float, default=10000.0)
    parser.add_argument("--y-min", type=float, default=None)
    parser.add_argument("--y-max", type=float, default=2600)
    parser.add_argument("--link-budget-log", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--plot-enabled", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument(
        "--step",
        type=int,
        default=None,
        help="Optional step index to use from --stepper-output-csv. Default is latest row.",
    )
    return parser.parse_args()


def _read_stepper_row(stepper_csv: Path, step: int | None = None) -> dict[str, Any] | None:
    if not stepper_csv.exists():
        return None

    target_row: dict[str, Any] | None = None
    with stepper_csv.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if step is None:
            for row in reader:
                target_row = row
            return target_row

        for row in reader:
            try:
                row_step = int(float(row.get("step", 0) or 0))
            except (TypeError, ValueError):
                continue
            if row_step == int(step):
                target_row = row
                break
    return target_row


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    stepper_csv = Path(args.stepper_output_csv)
    stepper_json = args.stepper_current_json or (output_dir / "satellite_steps_current_pos.json")
    stepper_row = _read_stepper_row(stepper_csv=stepper_csv, step=args.step)

    if stepper_row is not None and args.step is not None and args.sat_lat is None and args.sat_lon is None:
        requested_nodes = int(round(float(stepper_row.get("calculated_nodes", 0) or 0)))
        requested_demods = int(round(float(stepper_row.get("calculated_demodulators", 0) or 0)))
        sat_lat = float(stepper_row.get("sat_lat_deg", 0.0) or 0.0)
        sat_lon = float(stepper_row.get("sat_lon_deg", 0.0) or 0.0)
    else:
        stepper = SatelliteStepper(
            output_csv_path=stepper_csv,
            population_csv_path=args.population_csv,
            ocean_csv_path=args.ocean_csv,
            current_pos_json_path=stepper_json,
            node_population_ratio=float(args.node_population_ratio),
            demd_population_ratio=float(args.demd_population_ratio),
            minimum_frames=int(args.minimum_frames),
        )

        # Use current position by default; override lat/lon if provided.
        current_pos = stepper.get_pos()
        sat_lat = float(current_pos["latitude_deg"] if args.sat_lat is None else args.sat_lat)
        sat_lon = float(current_pos["longitude_deg"] if args.sat_lon is None else args.sat_lon)

        if args.sat_lat is not None or args.sat_lon is not None:
            est_row = stepper.estimate_row_for_lat_lon(sat_lat_deg=sat_lat, sat_lon_deg=sat_lon)
            requested_nodes = int(est_row.get("calculated_nodes", 0) or 0)
            requested_demods = int(est_row.get("calculated_demodulators", 0) or 0)
        else:
            cur_row = stepper.current()
            requested_nodes = int(cur_row.get("calculated_nodes", 0) or 0)
            requested_demods = int(cur_row.get("calculated_demodulators", 0) or 0)

    # Requested mapping:
    #   stepper nodes   -> selected_nodes (single exact point)
    #   stepper demods  -> num_decoders
    # node_points = 1
    # selected_nodes = [max(1, int(requested_nodes))]
    num_decoders = max(1, int(requested_demods))
    drop_mode = "hdrdd" if args.drop_mode == "headerdrop" else args.drop_mode

    lrfhss_root = Path(args.lrfhss_root).resolve()
    if str(lrfhss_root) not in sys.path:
        sys.path.insert(0, str(lrfhss_root))

    # try:
    #     import LRFHSS_simulator as sim
    # except ModuleNotFoundError as exc:
    #     raise ModuleNotFoundError(
    #         "Missing dependency while importing LRFHSS_simulator. "
    #         "Install required LR-FHSS deps (e.g. pip install galois)."
    #     ) from exc

    out_csv = output_dir / f"lrfhss_sim_cr{int(args.coding_rate)}_one_pos.csv"
    out_png = output_dir / f"lrfhss_demod_{int(num_decoders)}.png"
    
    print(f"Number of decoders to simulate: {num_decoders}")
    print(f"Number of nodes to simulate: {requested_nodes}")
    csv_path, png_path = sim.runsim2plot(
        num_decoders=int(num_decoders),
        drop_mode=str(drop_mode),
        filename=out_csv,
        coding_rate=int(args.coding_rate),
        metric=str(args.metric),
        include_lifan=bool(args.include_lifan),
        include_infp=bool(args.include_infp),
        inf_demods=args.inf_demods,
        node_min=args.node_min,
        node_max=args.node_max,
        # selected_nodes=selected_nodes,
        node_points=int(requested_nodes),
        runs_per_node=max(1, int(args.runs_per_node)),
        link_budget_log=bool(args.link_budget_log),
        plot_enabled=bool(args.plot_enabled),
        plot_filename=out_png,
        x_min=args.x_min,
        x_max=args.x_max,
        y_min=args.y_min,
        y_max=args.y_max,
        title=f"CR{int(args.coding_rate)} and {int(num_decoders)} demodulators",
    )

    print(f"lrfhss_png: {out_png.resolve()}")
    if elev_list is not None:
        # print(f"elevations: {elev_list}")
        for elev in elev_list:
            # demod_info = stepper.get_current_demodulators_for_elevation(elev)
            # print(f"Demodulator info for elevation {elev}: {demod_info}")
            # num_decoders=demod_info["busy"]
            node_info=stepper.get_current_nodes_for_elevation(elev)
            print(f"Node info for elevation {elev}: {node_info}")
            requested_nodes= node_info["num_nodes"]
            elev_out_csv = output_dir / f"lrfhss_sim_cr{int(args.coding_rate)}_elev{int(elev)}.csv"
            elev_out_png = output_dir / f"lrfhss_demod_{int(num_decoders)}_elev{int(elev)}.png"
            csv_path, png_path = sim.runsim2plot(
                num_decoders=int(num_decoders),
                drop_mode=str(drop_mode),
                filename=elev_out_csv,
                coding_rate=int(args.coding_rate),
                metric=str(args.metric),
                include_lifan=bool(args.include_lifan),
                include_infp=bool(args.include_infp),
                inf_demods=args.inf_demods,
                node_min=args.node_min,
                node_max=args.node_max,
                # selected_nodes=selected_nodes,
                node_points=int(requested_nodes),
                runs_per_node=max(1, int(args.runs_per_node)),
                link_budget_log=bool(args.link_budget_log),
                plot_enabled=bool(args.plot_enabled),
                plot_filename=elev_out_png,
                x_min=args.x_min,
                x_max=args.x_max,
                y_min=args.y_min,
                y_max=args.y_max,
                title=f"CR{int(args.coding_rate)}, {int(num_decoders)} demodulators, and {int(elev)}° elevation \n {int(requested_nodes)} nodes",
                fixed_elevation=int(elev),
            )
            print(f"lrfhss_png: {elev_out_png.resolve()}")
    # summary = {
    #     "sat_lat_deg": float(sat_lat),
    #     "sat_lon_deg": float(sat_lon),
    #     "requested_nodes": int(requested_nodes),
    #     "requested_demodulators": int(requested_demods),
    #     "node_points": int(node_points),
    #     "num_decoders": int(num_decoders),
    #     "drop_mode": str(drop_mode),
    #     "coding_rate": int(args.coding_rate),
    #     "metric": str(args.metric),
    #     "stepper_csv": str(Path(stepper_csv).resolve()),
    #     "stepper_current_json": str(Path(stepper_json).resolve()),
    #     "lrfhss_csv": str(Path(csv_path).resolve()),
    #     "lrfhss_plot_png": str(Path(png_path).resolve()) if png_path is not None else None,
    # }

    # summary_json = output_dir / "one_pos_summary.json"
    # with summary_json.open("w", encoding="utf-8") as f:
    #     json.dump(summary, f, indent=2)

    # summary_csv = output_dir / "one_pos_summary.csv"
    # with summary_csv.open("w", encoding="utf-8", newline="") as f:
    #     writer = csv.DictWriter(f, fieldnames=list(summary.keys()))
    #     writer.writeheader()
    #     writer.writerow(summary)

    # print(
    #     f"one_pos_done lat={summary['sat_lat_deg']:.6f} lon={summary['sat_lon_deg']:.6f} "
    #     f"node_points={summary['node_points']} num_decoders={summary['num_decoders']}"
    # )
    # print(f"lrfhss_csv={summary['lrfhss_csv']}")
    # if summary["lrfhss_plot_png"] is not None:
    #     print(f"lrfhss_plot_png={summary['lrfhss_plot_png']}")
    # print(f"summary_json={summary_json.resolve()}")
    # print(f"summary_csv={summary_csv.resolve()}")
    # return 0


if __name__ == "__main__":
    raise SystemExit(main())
