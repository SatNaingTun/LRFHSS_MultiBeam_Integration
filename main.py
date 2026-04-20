from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys
from typing import Any

from tqdm import tqdm
from LRFHSS import LRFHSS_simulator as sim,LoRaNetwork

from matplotlib import pyplot as plt

from modules.satellite_stepper import SatelliteStepper, _build_arg_parser
from ProjectConfig import node_population_ratio, demd_population_ratio, elev_list
from one_pos_lrfhss_sim import _read_stepper_row


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(
        description=(
            "One-position LR-FHSS run: get current nodes/demods from SatelliteStepper, "
            "then run LRFHSS_simulator.runsim2plot directly."
        )
    )
    parser.add_argument("--output-dir", type=Path, default=root / "results" / "multi_step_lrfhss", help="Directory to write output CSVs and PNGs.")
    parser.add_argument("--one_pos_output_dir", type=Path, default=root / "results" / "one_pos_2_multi_step_lrfhss", help="Directory to write one-position output CSVs and PNGs.")
    parser.add_argument("--sat-lat", type=float, default=None, help="Optional override latitude for node/demod estimate.")
    parser.add_argument("--sat-lon", type=float, default=None, help="Optional override longitude for node/demod estimate.")
    parser.add_argument(
        "--stepper-output-csv",
        type=Path,
        default=root / "results" / "multi_step_lrfhss" / "satellite_steps.csv",
        help="Satellite stepper CSV to use as source of calculated_nodes/calculated_demodulators.",
    )
    parser.add_argument(
        "--stepper-current-json",
        type=Path,
        default=None,
        help="Default: <output-dir>/satellite_steps_current_pos.json",
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=2,
        help="Number of next() steps to execute after initial row is written.",
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

def run_lrfhss_simulator_one_step(
    stepper: SatelliteStepper,args: argparse.Namespace, one_pos_output_dir: Path) -> dict[str, Any]:
        stepper.next()  # Advance to next position (or initial if first run).
        current_pos = stepper.get_pos()
        sat_lat = float(current_pos["latitude_deg"] if args.sat_lat is None else args.sat_lat)
        sat_lon = float(current_pos["longitude_deg"] if args.sat_lon is None else args.sat_lon)

        if args.sat_lat is not None or args.sat_lon is not None:
                est_row = stepper.estimate_row_for_lat_lon(sat_lat_deg=sat_lat, sat_lon_deg=sat_lon)
                step_row = est_row
                requested_nodes = int(est_row.get("calculated_nodes", 0) or 0)
                requested_demods = int(est_row.get("calculated_demodulators", 0) or 0)
        else:
                cur_row = stepper.current()
                step_row = cur_row
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

        
        out_csv = one_pos_output_dir / f"lrfhss_sim_cr{int(args.coding_rate)}_one_pos.csv"
        out_png = one_pos_output_dir / f"lrfhss_demod_{int(num_decoders)}.png"
        
        # sim.runsim2csv(
        #     num_decoders=int(num_decoders),
        #     drop_mode=str(drop_mode),
        #     filename=out_csv,
        #     coding_rate=int(args.coding_rate),
        #     metric=str(args.metric),
        #     include_lifan=bool(args.include_lifan),
        #     include_infp=bool(args.include_infp),
        #     inf_demods=args.inf_demods,
        #     node_min=args.node_min,
        #     node_max=args.node_max,
        #     # selected_nodes=selected_nodes,
        #     node_points=int(requested_nodes),
        #     runs_per_node=max(1, int(args.runs_per_node)),
        #     link_budget_log=bool(args.link_budget_log),
        #     # plot_enabled=bool(args.plot_enabled),
        #     # plot_filename=out_png,
        #     # x_min=args.x_min,
        #     # x_max=args.x_max,
        #     # y_min=args.y_min,
        #     # y_max=args.y_max,
        #     # title=f"CR{int(args.coding_rate)} and {int(num_decoders)} demodulators",
        # )

        # print(f"lrfhss_png: {out_png.resolve()}")
        if elev_list is not None:
            # print(f"elevations: {elev_list}")
            pbar = tqdm(elev_list)

            for elev in pbar:
                # Update the description with the current elevation
                pbar.set_description(f"Processing Elevation: {elev}°")
                        
                # demod_info = stepper.get_current_demodulators_for_elevation(elev)
                # print(f"Demodulator info for elevation {elev}: {demod_info}")
                # num_decoders=demod_info["busy"]
                node_info=stepper.get_current_nodes_for_elevation(elev)
                print(f"Node info for elevation {elev}: {node_info}")
                requested_nodes= node_info["num_nodes"]
                elev_out_csv = one_pos_output_dir / f"lrfhss_sim_cr{int(args.coding_rate)}_elev{int(elev)}.csv"
                elev_out_png = one_pos_output_dir / f"lrfhss_demod_{int(num_decoders)}_elev{int(elev)}.png"
                sim.runsim2plot(
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
                # print(f"lrfhss_png: {elev_out_png.resolve()}")
        return {
            "step": int(step_row.get("step", current_pos.get("step", 0)) or 0),
            "orbit_index": int(step_row.get("orbit_index", current_pos.get("orbit_index", 0)) or 0),
            "timestamp_s": float(step_row.get("timestamp_s", current_pos.get("timestamp_s", 0.0)) or 0.0),
            "timestamp_utc": str(step_row.get("timestamp_utc", "")),
        }


def append_one_pos_csvs_to_output_dir(
    one_pos_output_dir: Path,
    output_dir: Path,
    step_meta: dict[str, Any],
) -> None:
    csv_files = sorted(one_pos_output_dir.glob("*.csv"))
    if not csv_files:
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    step = int(step_meta.get("step", 0) or 0)
    orbit_index = int(step_meta.get("orbit_index", 0) or 0)
    timestamp_s = float(step_meta.get("timestamp_s", 0.0) or 0.0)
    timestamp_utc = str(step_meta.get("timestamp_utc", ""))

    for src_csv in csv_files:
        dst_csv = output_dir / f"{src_csv.stem}_steps.csv"
        with src_csv.open("r", encoding="utf-8", newline="") as src_f:
            src_rows = [row for row in csv.reader(src_f) if row]
        if not src_rows:
            continue

        payload_len = max(len(row) for row in src_rows)
        if dst_csv.exists() and dst_csv.stat().st_size > 0:
            with dst_csv.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, [])
            existing_payload_len = max(0, len(header) - 4)
            payload_len = max(payload_len, existing_payload_len)

        write_header = (not dst_csv.exists()) or dst_csv.stat().st_size == 0
        with dst_csv.open("a", encoding="utf-8", newline="") as dst_f:
            writer = csv.writer(dst_f)
            if write_header:
                writer.writerow(
                    [
                        "step",
                        "orbit_index",
                        "timestamp_s",
                        "timestamp_utc",
                    ] + [f"value_{i}" for i in range(payload_len)]
                )

            for row in src_rows:
                padded = list(row) + [""] * max(0, payload_len - len(row))
                writer.writerow(
                    [
                        step,
                        orbit_index,
                        f"{timestamp_s:.6f}",
                        timestamp_utc,
                    ] + padded
                )


def _parse_pipe_floats(text: str) -> list[float]:
    values: list[float] = []
    for token in str(text).split("|"):
        t = token.strip()
        if not t:
            continue
        try:
            values.append(float(t))
        except ValueError:
            continue
    return values


def plot_orbit_time_vs_decoded_packets(output_dir: Path) -> list[Path]:
    plots_dir = output_dir / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)

    out_paths: list[Path] = []
    step_csvs = sorted(output_dir.glob("lrfhss_sim_*_steps.csv"))
    for step_csv in step_csvs:
        if "link_budget_agg" in step_csv.stem:
            continue

        series_by_key: dict[str, list[tuple[float, float]]] = {}
        with step_csv.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                row_key = str(row.get("value_0", "")).strip()
                if not row_key:
                    row_key = str(row.get("row_key", "")).strip()
                if "dec_payld" not in row_key:
                    continue
                try:
                    orbit_t = float(row.get("timestamp_s", 0.0) or 0.0)
                except (TypeError, ValueError):
                    continue
                value_keys = [k for k in row.keys() if k.startswith("value_")]
                value_keys_sorted = sorted(value_keys, key=lambda k: int(k.split("_", 1)[1]))
                values: list[float] = []
                for k in value_keys_sorted[1:]:
                    token = str(row.get(k, "")).strip()
                    if not token:
                        continue
                    try:
                        values.append(float(token))
                    except ValueError:
                        continue
                if not values:
                    values = _parse_pipe_floats(str(row.get("row_values_pipe", "")))
                if not values:
                    continue
                decoded_mean = float(sum(values) / len(values))
                series_by_key.setdefault(row_key, []).append((orbit_t, decoded_mean))

        if not series_by_key:
            continue

        fig, ax = plt.subplots(figsize=(10, 5.5))
        for row_key, pts in sorted(series_by_key.items()):
            pts_sorted = sorted(pts, key=lambda x: x[0])
            xs = [p[0] for p in pts_sorted]
            ys = [p[1] for p in pts_sorted]
            ax.plot(xs, ys, marker="o", linewidth=1.8, markersize=3.5, label=row_key)

        ax.set_title(f"Orbit Time vs Decoded Packets ({step_csv.stem})")
        ax.set_xlabel("orbit_timestamp_s")
        ax.set_ylabel("decoded_packets_mean")
        ax.grid(True, linestyle="-", linewidth=0.5, alpha=0.35)
        ax.legend(fontsize=8)
        fig.tight_layout()

        out_png = plots_dir / f"orbit_time_vs_decoded_packets_{step_csv.stem}.png"
        fig.savefig(out_png, dpi=220)
        plt.close(fig)
        out_paths.append(out_png)

    return out_paths




def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    one_pos_output_dir = Path(args.one_pos_output_dir)
    one_pos_output_dir.mkdir(parents=True, exist_ok=True)

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
        steps=args.steps if args.steps is not None else 1
        for _ in tqdm(range(steps),desc="Steps"):
            # last_row = stepper.next()
            # Use current position by default; override lat/lon if provided.
            step_meta = run_lrfhss_simulator_one_step(stepper=stepper, args=args, one_pos_output_dir=one_pos_output_dir)
            append_one_pos_csvs_to_output_dir(
                one_pos_output_dir=one_pos_output_dir,
                output_dir=output_dir,
                step_meta=step_meta,
            )
            plot_paths = plot_orbit_time_vs_decoded_packets(output_dir=output_dir)
            for p in plot_paths:
                print(f"decoded_packets_plot= {p}")
            
        


if __name__ == "__main__":
    raise SystemExit(main())
