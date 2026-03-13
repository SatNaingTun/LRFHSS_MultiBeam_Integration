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


def power_mode(nodes):
    if nodes == 0:
        return "sleep"
    elif nodes < 200:
        return "idle"
    else:
        return "busy"


@dataclass
class PipelineConfig:
    node_loads: list[int]
    demodulator_options: list[int]
    runs_per_point: int
    visibility_min_elev_deg: float
    output_dir: Path
    seed: int


def initialize_simulation_parameters(
    output_dir: Path,
    seed: int,
    node_min: int,
    node_max: int,
    node_points: int,
    demodulator_options: list[int],
    nodes_list: list[int] | None,
) -> PipelineConfig:
    if nodes_list:
        loads = sorted(set(int(v) for v in nodes_list if int(v) >= 0))
    else:
        loads = [int(round(v)) for v in np.logspace(np.log10(node_min), np.log10(node_max), num=node_points)]
        loads = sorted(set(loads))
    return PipelineConfig(
        node_loads=loads,
        demodulator_options=demodulator_options,
        runs_per_point=1,
        visibility_min_elev_deg=10.0,
        output_dir=output_dir,
        seed=seed,
    )


def compute_satellite_orbit(network_geometry):
    sat_pos = network_geometry.get_satellite_pos()
    sat_pos[:, 38537] = np.array([0, 0, 600e3])
    return sat_pos


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

    return {"visible_mask": visible, "elevation_deg": elev_deg, "windows": windows}


def generate_iot_nodes(node_count: int):
    return list(range(node_count))


def assign_lrfhss_packets(nodes: list[int]):
    return len(nodes)


def check_satellite_visibility(visibility_info: dict):
    windows = visibility_info["windows"]
    if not windows:
        return False, None
    first_window = windows[0]
    selected_frame = (first_window[0] + first_window[1]) // 2
    return True, int(selected_frame)


def select_satellite_power_mode(nodes: int):
    return power_mode(nodes)


def transmit_fragments(packet_count: int, visible: bool):
    return packet_count if visible else 0


def detect_collisions(decoded_metrics: dict):
    return int(decoded_metrics["collided"])


def allocate_demodulators(requested_demods: int, mode: str):
    if mode == "sleep":
        return 0
    return requested_demods


def baseline_packet_decoding(LoRaNetwork, node_count: int, demods: int, use_earlydecode: bool, use_earlydrop: bool):
    if node_count <= 0 or demods <= 0:
        return {
            "tracked_txs": 0,
            "decoded_payloads": 0,
            "decoded_bytes": 0,
            "collided": 0,
        }

    network = LoRaNetwork(
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
    network.run(False, False)

    return {
        "tracked_txs": int(network.get_tracked_txs()),
        "decoded_payloads": int(network.get_decoded_hrd_pld()),
        "decoded_bytes": int(network.get_decoded_bytes()),
        "collided": int(network.get_collided_hdr_pld()),
    }


def store_metrics(records: list[dict], output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "heavy_load_metrics.json"
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)

    csv_path = output_dir / "heavy_load_metrics.csv"
    if records:
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(records[0].keys()))
            writer.writeheader()
            writer.writerows(records)

    return json_path, csv_path


def generate_performance_plots(records: list[dict], output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)

    colors = ["#1f77b4", "#2ca02c", "#9467bd", "#d62728", "#17becf", "#8c564b"]

    # Plot 1: all series
    series = {}
    for r in records:
        key = (r["mode_label"], r["requested_demods"])
        series.setdefault(key, {"x": [], "y": []})
        series[key]["x"].append(r["nodes"])
        series[key]["y"].append(r["decoded_payloads"])

    fig, ax = plt.subplots(figsize=(9, 6))
    for idx, ((mode_label, demods), vals) in enumerate(sorted(series.items(), key=lambda t: (t[0][1], t[0][0]))):
        x = np.array(vals["x"])
        y = np.array(vals["y"])
        order = np.argsort(x)
        line_style = "-"
        ax.plot(
            x[order],
            y[order],
            linestyle=line_style,
            marker="o",
            linewidth=1.6,
            markersize=4,
            color=colors[idx % len(colors)],
            label=f"{mode_label} {demods} demods",
        )

    ax.set_xscale("symlog", linthresh=1)
    ax.set_xlabel("Number of Nodes (Traffic Load)")
    ax.set_ylabel("Decoded Payloads")
    ax.set_title("Heavy Load Test for Demodulator Constraints")
    ax.grid(True, which="both", linestyle=":", alpha=0.5)
    ax.legend()
    fig.tight_layout()
    all_plot = output_dir / "heavy_load_demodulator_constraints.png"
    fig.savefig(all_plot, dpi=200)
    plt.close(fig)

    # Plot 2: split by power mode
    mode_names = [m for m in ["sleep", "idle", "busy"] if any(r["power_mode"] == m for r in records)]
    nrows = len(mode_names)
    fig2, axes = plt.subplots(nrows=nrows, ncols=1, figsize=(10, 4 * max(1, nrows)), sharex=True)
    if nrows == 1:
        axes = [axes]

    for ax, p_mode in zip(axes, mode_names):
        sub = [r for r in records if r["power_mode"] == p_mode]
        mode_series = {}
        for r in sub:
            key = (r["mode_label"], r["requested_demods"])
            mode_series.setdefault(key, {"x": [], "y": []})
            mode_series[key]["x"].append(r["nodes"])
            mode_series[key]["y"].append(r["decoded_payloads"])

        for idx, ((mode_label, demods), vals) in enumerate(sorted(mode_series.items(), key=lambda t: (t[0][1], t[0][0]))):
            x = np.array(vals["x"])
            y = np.array(vals["y"])
            order = np.argsort(x)
            line_style = "-"
            ax.plot(
                x[order],
                y[order],
                linestyle=line_style,
                marker="o",
                linewidth=1.4,
                markersize=3.5,
                color=colors[idx % len(colors)],
                label=f"{mode_label} {demods} demods",
            )

        ax.set_xscale("symlog", linthresh=1)
        ax.set_ylabel("Decoded Payloads")
        ax.set_title(f"Power Mode: {p_mode}")
        ax.grid(True, which="both", linestyle=":", alpha=0.5)
        ax.legend(loc="best", fontsize=8)

    axes[-1].set_xlabel("Number of Nodes (Traffic Load)")
    fig2.tight_layout()
    mode_plot = output_dir / "decoded_payloads_by_power_mode.png"
    fig2.savefig(mode_plot, dpi=200)
    plt.close(fig2)

    return {"all_series": all_plot, "by_power_mode": mode_plot}


def run_workflow(
    multi_beam_root: Path,
    lrfhss_root: Path,
    output_dir: Path,
    seed: int,
    node_min: int,
    node_max: int,
    node_points: int,
    demodulator_options: list[int],
    nodes_list: list[int] | None,
):
    # START
    cfg = initialize_simulation_parameters(
        output_dir=output_dir,
        seed=seed,
        node_min=node_min,
        node_max=node_max,
        node_points=node_points,
        demodulator_options=demodulator_options,
        nodes_list=nodes_list,
    )

    _, network_geometry, _, utils_mod, LoRaNetwork = bootstrap(multi_beam_root, lrfhss_root)

    random.seed(cfg.seed)
    np.random.seed(cfg.seed)

    sat_pos = compute_satellite_orbit(network_geometry)
    visibility_info = generate_visibility_windows(sat_pos, utils_mod, cfg.visibility_min_elev_deg)

    all_records = []

    for nodes in cfg.node_loads:
        iot_nodes = generate_iot_nodes(nodes)
        packet_count = assign_lrfhss_packets(iot_nodes)
        visible, selected_frame = check_satellite_visibility(visibility_info)
        p_mode = select_satellite_power_mode(nodes)
        tx_count = transmit_fragments(packet_count, visible)

        for requested_demods in cfg.demodulator_options:
            allocated_demods = allocate_demodulators(requested_demods, p_mode)

            mode_options = [("Baseline", False, False)]

            for mode_label, use_earlydecode, use_earlydrop in mode_options:
                decoded_payload_runs = []
                tracked_runs = []
                decoded_bytes_runs = []
                collision_runs = []

                for run_idx in range(cfg.runs_per_point):
                    random.seed(cfg.seed + nodes * 100 + requested_demods * 10 + run_idx + (1 if use_earlydecode else 0))
                    decode_metrics = baseline_packet_decoding(
                        LoRaNetwork=LoRaNetwork,
                        node_count=tx_count,
                        demods=allocated_demods,
                        use_earlydecode=use_earlydecode,
                        use_earlydrop=use_earlydrop,
                    )
                    collision_runs.append(detect_collisions(decode_metrics))
                    decoded_payload_runs.append(decode_metrics["decoded_payloads"])
                    tracked_runs.append(decode_metrics["tracked_txs"])
                    decoded_bytes_runs.append(decode_metrics["decoded_bytes"])

                all_records.append(
                    {
                        "nodes": int(nodes),
                        "power_mode": p_mode,
                        "visible": bool(visible),
                        "selected_frame": int(selected_frame) if selected_frame is not None else -1,
                        "requested_demods": int(requested_demods),
                        "allocated_demods": int(allocated_demods),
                        "mode_label": mode_label,
                        "decoded_payloads": float(np.mean(decoded_payload_runs)),
                        "tracked_txs": float(np.mean(tracked_runs)),
                        "decoded_bytes": float(np.mean(decoded_bytes_runs)),
                        "collided": float(np.mean(collision_runs)),
                    }
                )

    metrics_json, metrics_csv = store_metrics(all_records, cfg.output_dir)
    plot_paths = generate_performance_plots(all_records, cfg.output_dir)

    summary = {
        "workflow": [
            "START",
            "Initialize simulation parameters",
            "Compute satellite orbit",
            "Generate visibility windows",
            "Generate IoT nodes",
            "Assign LR-FHSS packets",
            "Check satellite visibility",
            "Select satellite power mode",
            "Transmit fragments",
            "Detect collisions",
            "Allocate demodulators",
            "Baseline packet decoding",
            "Store metrics",
            "Generate performance plots",
            "END",
        ],
        "power_mode_logic": {"0": "sleep", "1_to_199": "idle", "200_plus": "busy"},
        "node_range": {"min": node_min, "max": node_max, "points": node_points},
        "metrics_json": str(metrics_json.resolve()),
        "metrics_csv": str(metrics_csv.resolve()),
        "plots": {k: str(v.resolve()) for k, v in plot_paths.items()},
        "visibility_windows": visibility_info["windows"],
    }

    summary_path = cfg.output_dir / "workflow_summary.json"
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("Workflow completed.")
    print(f"Metrics JSON: {metrics_json.resolve()}")
    print(f"Metrics CSV:  {metrics_csv.resolve()}")
    for name, p in plot_paths.items():
        print(f"Plot ({name}): {p.resolve()}")
    print(f"Summary:      {summary_path.resolve()}")
    # END
