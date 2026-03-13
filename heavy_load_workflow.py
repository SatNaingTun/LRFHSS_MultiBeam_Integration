import argparse
import csv
import json
import random
from dataclasses import dataclass
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from external_repos import bootstrap


# -----------------------------
# START
# -----------------------------


def power_mode(nodes):
    if nodes == 0:
        return "sleep"
    elif nodes < 200:
        return "idle"
    else:
        return "busy"


@dataclass
class SimParams:
    node_loads: list[int]
    demodulator_options: list[int]
    compare_early_decode: bool
    runs_per_point: int
    visibility_min_elev_deg: float
    output_dir: Path
    seed: int


def initialize_simulation_parameters(output_dir: Path, seed: int) -> SimParams:
    node_loads = [int(round(v)) for v in np.logspace(2, 4, num=12)]
    node_loads = sorted(set(node_loads))
    return SimParams(
        node_loads=node_loads,
        demodulator_options=[10, 100, 1000],
        compare_early_decode=True,
        runs_per_point=1,
        visibility_min_elev_deg=10.0,
        output_dir=output_dir,
        seed=seed,
    )


# -----------------------------
# Satellite Orbit Model
# -----------------------------

def compute_satellite_orbit(network_geometry):
    sat_pos = network_geometry.get_satellite_pos()
    sat_pos[:, 38537] = np.array([0, 0, 600e3])
    return sat_pos


# -----------------------------
# Coverage Footprint / Visibility
# -----------------------------

def generate_visibility_windows(sat_pos: np.ndarray, utils_mod, min_elev_deg: float):
    elev_deg = utils_mod.get_elevation_angle_from_center(sat_pos[0, :], sat_pos[2, :]) * 180.0 / np.pi
    visible = elev_deg >= min_elev_deg

    windows = []
    start = None
    for i, is_visible in enumerate(visible):
        if is_visible and start is None:
            start = i
        if (not is_visible) and start is not None:
            windows.append((start, i - 1))
            start = None
    if start is not None:
        windows.append((start, len(visible) - 1))

    return {
        "visible_mask": visible,
        "elevation_deg": elev_deg,
        "windows": windows,
    }


def pick_visible_frame(visibility_info: dict):
    windows = visibility_info["windows"]
    if not windows:
        return None
    first_window = windows[0]
    return (first_window[0] + first_window[1]) // 2


# -----------------------------
# IoT Nodes + LR-FHSS packets
# -----------------------------

def generate_iot_nodes(node_count: int):
    return list(range(node_count))


def assign_lrfhss_packets(nodes: list[int]):
    return len(nodes)


# -----------------------------
# Channel Model + Visibility check
# -----------------------------

def check_satellite_visibility(selected_frame, visibility_info: dict):
    if selected_frame is None:
        return False
    return bool(visibility_info["visible_mask"][selected_frame])


def channel_model(packet_count: int, visible: bool):
    return packet_count if visible else 0


# -----------------------------
# Demod + decoding
# -----------------------------

def select_satellite_power_mode(node_count: int):
    return power_mode(node_count)


def allocate_demodulators(base_demods: int, mode: str):
    if mode == "sleep":
        return 0
    return base_demods


def baseline_packet_decoding(
    LoRaNetwork,
    node_count: int,
    demods: int,
    use_earlydecode: bool,
    use_earlydrop: bool,
):
    if node_count <= 0 or demods <= 0:
        return {
            "tracked_txs": 0,
            "decoded_payloads": 0,
            "decoded_bytes": 0,
            "collided": 0,
        }

    net = LoRaNetwork(
        node_count,
        "driver",
        1,
        280,
        8,
        1,
        6,
        25,
        228,
        demods,
        use_earlydecode,
        use_earlydrop,
        False,
        "strict",
    )
    net.run(False, False)

    return {
        "tracked_txs": int(net.get_tracked_txs()),
        "decoded_payloads": int(net.get_decoded_hrd_pld()),
        "decoded_bytes": int(net.get_decoded_bytes()),
        "collided": int(net.get_collided_hdr_pld()),
    }


# -----------------------------
# Metrics + plots
# -----------------------------

def store_metrics(records: list[dict], output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "heavy_load_metrics.json"
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)

    csv_path = output_dir / "heavy_load_metrics.csv"
    if records:
        keys = list(records[0].keys())
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(records)

    return json_path, csv_path


def generate_performance_plots(records: list[dict], output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)

    # group by series
    series = {}
    for r in records:
        key = (r["mode_label"], r["requested_demods"])
        series.setdefault(key, {"x": [], "y": []})
        series[key]["x"].append(r["nodes"])
        series[key]["y"].append(r["decoded_payloads"])

    fig, ax = plt.subplots(figsize=(9, 6))
    colors = {10: "#1f77b4", 100: "#2ca02c", 1000: "#9467bd"}

    for (mode_label, demods), vals in sorted(series.items(), key=lambda t: (t[0][1], t[0][0])):
        x = np.array(vals["x"])
        y = np.array(vals["y"])
        order = np.argsort(x)
        x = x[order]
        y = y[order]

        ls = "--" if mode_label == "Early" else "-"
        ax.plot(
            x,
            y,
            linestyle=ls,
            marker="o",
            linewidth=1.6,
            markersize=4,
            color=colors.get(demods, None),
            label=f"{mode_label} {demods} demods",
        )

    ax.set_xscale("log")
    ax.set_xlabel("Number of Nodes (Traffic Load)")
    ax.set_ylabel("Decoded Payloads")
    ax.set_title("Heavy Load Test for Demodulator Constraints")
    ax.grid(True, which="both", linestyle=":", alpha=0.5)
    ax.legend()

    fig.tight_layout()
    out = output_dir / "heavy_load_demodulator_constraints.png"
    fig.savefig(out, dpi=200)
    plt.close(fig)

    return out


# -----------------------------
# END-TO-END WORKFLOW
# -----------------------------

def run_workflow(multi_beam_root: Path, lrfhss_root: Path, output_dir: Path, seed: int):
    # Initialize simulation parameters
    sim = initialize_simulation_parameters(output_dir=output_dir, seed=seed)

    # Load external project modules
    _, networkGeometry, _, utils_mod, LoRaNetwork = bootstrap(multi_beam_root, lrfhss_root)

    random.seed(sim.seed)
    np.random.seed(sim.seed)

    # Compute satellite orbit
    sat_pos = compute_satellite_orbit(networkGeometry)

    # Generate visibility windows
    visibility = generate_visibility_windows(sat_pos, utils_mod, sim.visibility_min_elev_deg)
    selected_frame = pick_visible_frame(visibility)

    all_records = []

    for nodes in sim.node_loads:
        # Generate IoT nodes
        node_list = generate_iot_nodes(nodes)

        # Assign LR-FHSS packets
        packet_count = assign_lrfhss_packets(node_list)

        # Check satellite visibility
        visible = check_satellite_visibility(selected_frame, visibility)

        # Select satellite power mode
        p_mode = select_satellite_power_mode(nodes)

        # Channel model
        channel_packets = channel_model(packet_count, visible)

        for demods in sim.demodulator_options:
            # Allocate demodulators
            alloc_demods = allocate_demodulators(demods, p_mode)

            modes = [("Baseline", False, False)]
            if sim.compare_early_decode:
                modes.append(("Early", True, True))

            for mode_label, use_earlydecode, use_earlydrop in modes:
                decoded_payloads_runs = []
                tracked_runs = []
                decoded_bytes_runs = []
                collided_runs = []

                for run_idx in range(sim.runs_per_point):
                    random.seed(sim.seed + nodes * 100 + demods * 10 + run_idx + (1 if use_earlydecode else 0))

                    # Baseline packet decoding
                    metrics = baseline_packet_decoding(
                        LoRaNetwork=LoRaNetwork,
                        node_count=channel_packets,
                        demods=alloc_demods,
                        use_earlydecode=use_earlydecode,
                        use_earlydrop=use_earlydrop,
                    )
                    decoded_payloads_runs.append(metrics["decoded_payloads"])
                    tracked_runs.append(metrics["tracked_txs"])
                    decoded_bytes_runs.append(metrics["decoded_bytes"])
                    collided_runs.append(metrics["collided"])

                record = {
                    "nodes": int(nodes),
                    "power_mode": p_mode,
                    "visible": bool(visible),
                    "selected_frame": int(selected_frame) if selected_frame is not None else -1,
                    "requested_demods": int(demods),
                    "allocated_demods": int(alloc_demods),
                    "mode_label": mode_label,
                    "decoded_payloads": float(np.mean(decoded_payloads_runs)),
                    "tracked_txs": float(np.mean(tracked_runs)),
                    "decoded_bytes": float(np.mean(decoded_bytes_runs)),
                    "collided": float(np.mean(collided_runs)),
                }
                all_records.append(record)

    json_path, csv_path = store_metrics(all_records, sim.output_dir)
    plot_path = generate_performance_plots(all_records, sim.output_dir)

    summary = {
        "records": len(all_records),
        "visibility_windows": visibility["windows"],
        "selected_frame": selected_frame,
        "metrics_json": str(json_path.resolve()),
        "metrics_csv": str(csv_path.resolve()),
        "plot": str(plot_path.resolve()),
    }

    summary_path = sim.output_dir / "heavy_load_summary.json"
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("Workflow completed.")
    print(f"Metrics JSON: {json_path.resolve()}")
    print(f"Metrics CSV:  {csv_path.resolve()}")
    print(f"Plot:         {plot_path.resolve()}")
    print(f"Summary:      {summary_path.resolve()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Heavy-load LR-FHSS demodulator workflow")
    parser.add_argument(
        "--multi-beam-root",
        type=Path,
        default=Path(r"c:\Users\satnaingtun.DESKTOP-4FQHRHU\Documents\SatNaingTun\NII_Projects\SNT\Multi-Beam-LEO-Framework"),
    )
    parser.add_argument(
        "--lrfhss-root",
        type=Path,
        default=Path(r"c:\Users\satnaingtun.DESKTOP-4FQHRHU\Documents\SatNaingTun\NII_Projects\SNT\LR-FHSS_LEO"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("results/heavy_load"),
    )
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    run_workflow(
        multi_beam_root=args.multi_beam_root,
        lrfhss_root=args.lrfhss_root,
        output_dir=args.output_dir,
        seed=args.seed,
    )

# -----------------------------
# END
# -----------------------------
