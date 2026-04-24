from __future__ import annotations

import argparse
import csv
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
            "then run LRFHSS_simulator.runsim2plot directly. "
            "If --given-nodes is provided, node calculation is skipped."
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
    parser.add_argument(
        "--given-nodes",
        type=int,
        default=None,
        help="Override fixed node count. If omitted, profile defaults are used (dense=10000, sparse=100).",
    )
    parser.add_argument(
        "--profile",
        type=str,
        choices=["dense", "sparse"],
        default="dense",
        help="Node-density profile. dense->10000 nodes, sparse->100 nodes.",
    )

    parser.add_argument("--lrfhss-root", type=Path, default=root / "LRFHSS")
    parser.add_argument("--coding-rate", type=int, default=1)
    parser.add_argument("--metric", type=str, default="dec_payld")
    parser.add_argument("--drop-mode", type=str, default="rlydd", choices=["rlydd", "hdrdd", "headerdrop"])
    parser.add_argument("--runs-per-node", type=int, default=1)
    parser.add_argument("--include-lifan", action="store_true")
    parser.add_argument("--infp", type=str, choices=["on", "off"], default="on")
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


def _run(args: argparse.Namespace, fixed_nodes: int | None = None) -> int:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    include_infp = str(args.infp).strip().lower() == "on"

    final_fixed_nodes = fixed_nodes
    if final_fixed_nodes is None and args.given_nodes is not None:
        final_fixed_nodes = max(1, int(args.given_nodes))

    stepper_csv = Path(args.stepper_output_csv)
    stepper_json = args.stepper_current_json or (output_dir / "satellite_steps_current_pos.json")
    stepper_row = _read_stepper_row(stepper_csv=stepper_csv, step=args.step)
    stepper: SatelliteStepper | None = None

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

    if final_fixed_nodes is not None:
        requested_nodes = int(final_fixed_nodes)
    output_node_suffix = f"_given_nodes{int(final_fixed_nodes)}" if args.given_nodes is not None else ""

    num_decoders = max(1, int(requested_demods))
    drop_mode = "hdrdd" if args.drop_mode == "headerdrop" else args.drop_mode

    lrfhss_root = Path(args.lrfhss_root).resolve()
    if str(lrfhss_root) not in sys.path:
        sys.path.insert(0, str(lrfhss_root))

    elevations = args.elev_list if args.elev_list is not None else elev_list
    if elevations is not None:
        if stepper is None and final_fixed_nodes is None:
            stepper = SatelliteStepper(
                output_csv_path=stepper_csv,
                population_csv_path=args.population_csv,
                ocean_csv_path=args.ocean_csv,
                current_pos_json_path=stepper_json,
                node_population_ratio=float(args.node_population_ratio),
                demd_population_ratio=float(args.demd_population_ratio),
                minimum_frames=int(args.minimum_frames),
            )
        for elev in elevations:
            if final_fixed_nodes is not None:
                requested_nodes = int(final_fixed_nodes)
                distance_km = float("nan")
            else:
                node_info = stepper.get_current_nodes_for_elevation(elev)
                print(f"Node info for elevation {elev}: {node_info}")
                requested_nodes = int(node_info["num_nodes"])
                distance_km = float(node_info.get("distance_km", float("nan")))

            elev_out_csv = output_dir / f"lrfhss_sim_cr{int(args.coding_rate)}_elev{int(elev)}{output_node_suffix}.csv"
            elev_out_png = output_dir / f"lrfhss_demod_{int(num_decoders)}_elev{int(elev)}{output_node_suffix}.png"
            csv_path, png_path = sim.runsim2plot(
                num_decoders=int(num_decoders),
                drop_mode=str(drop_mode),
                filename=elev_out_csv,
                coding_rate=int(args.coding_rate),
                metric=str(args.metric),
                include_lifan=bool(args.include_lifan),
                include_infp=include_infp,
                inf_demods=args.inf_demods,
                node_min=args.node_min,
                node_max=args.node_max,
                node_points=int(requested_nodes),
                runs_per_node=max(1, int(args.runs_per_node)),
                link_budget_log=bool(args.link_budget_log),
                plot_enabled=bool(args.plot_enabled),
                plot_filename=elev_out_png,
                x_min=args.x_min,
                x_max=args.x_max,
                y_min=args.y_min,
                y_max=args.y_max,
                title=(
                    f"Elev {int(elev)}deg | CR{int(args.coding_rate)}  | mode={str(drop_mode)} | \n"
                    f"nodes={int(requested_nodes)}"
                    + (
                        f" | dist={float(distance_km):.1f} km \n"
                        if distance_km == distance_km
                        else ""
                    )
                    + " | "
                    # f"INFP={'on' if include_infp else 'off'} | inf_demods="
                    f"{'auto' if args.inf_demods is None else int(args.inf_demods)} | \n"
                    f"lifan={'on' if bool(args.include_lifan) else 'off'}"
                ),
                fixed_elevation=int(elev),
            )
            _ = csv_path, png_path
            print(f"lrfhss_png: {elev_out_png.resolve()}")

    return 0


def dense(args: argparse.Namespace | None = None) -> int:
    local_args = args or parse_args()
    default_nodes = 10000 if local_args.given_nodes is None else int(local_args.given_nodes)
    return _run(local_args, fixed_nodes=max(1, default_nodes))


def sparse(args: argparse.Namespace | None = None) -> int:
    local_args = args or parse_args()
    default_nodes = 100 if local_args.given_nodes is None else int(local_args.given_nodes)
    return _run(local_args, fixed_nodes=max(1, default_nodes))


def main() -> int:
    args = parse_args()
    if str(args.profile).strip().lower() == "sparse":
        return sparse(args)
    return dense(args)


if __name__ == "__main__":
    raise SystemExit(main())
