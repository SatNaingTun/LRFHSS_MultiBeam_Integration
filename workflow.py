import json
import random
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from common_workflow_outputs import export_metrics, generate_performance_plots
from lrfhss_connector import load_lrfhss_components
from multi_beam_connector import load_multi_beam_modules


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
    export_csv: bool
    generate_plots: bool


def initialize_simulation_parameters(
    output_dir: Path,
    seed: int,
    node_min: int,
    node_max: int,
    node_points: int,
    demodulator_options: list[int],
    nodes_list: list[int] | None,
    export_csv: bool,
    generate_plots: bool,
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
        export_csv=export_csv,
        generate_plots=generate_plots,
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
        numNodes=node_count,
        familyname="driver",
        numOCW=7,
        numOBW=280,
        numGrids=8,
        CR=1,
        timeGranularity=6,
        freqGranularity=25,
        simTime=228,
        numDecoders=demods,
        use_earlydecode=use_earlydecode,
        use_earlydrop=use_earlydrop,
        use_headerdrop=False,
        collision_method="strict",
    )
    network.run(False, False)

    return {
        "tracked_txs": int(network.get_tracked_txs()),
        "decoded_payloads": int(network.get_decoded_hrd_pld()),
        "decoded_bytes": int(network.get_decoded_bytes()),
        "collided": int(network.get_collided_hdr_pld()),
    }


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
    export_csv: bool,
    generate_plots: bool,
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
        export_csv=export_csv,
        generate_plots=generate_plots,
    )

    _, network_geometry, _, utils_mod = load_multi_beam_modules(multi_beam_root)
    LoRaNetwork = load_lrfhss_components(lrfhss_root)

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

    metrics_json, metrics_csv = export_metrics(all_records, cfg.output_dir, cfg.export_csv)
    plot_paths = generate_performance_plots(all_records, cfg.output_dir) if cfg.generate_plots else {}

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
        "metrics_csv": str(metrics_csv.resolve()) if metrics_csv else None,
        "plots": {k: str(v.resolve()) for k, v in plot_paths.items()},
        "visibility_windows": visibility_info["windows"],
        "export_csv": bool(cfg.export_csv),
        "generate_plots": bool(cfg.generate_plots),
    }

    summary_path = cfg.output_dir / "workflow_summary.json"
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("Workflow completed.")
    print(f"Metrics JSON: {metrics_json.resolve()}")
    if metrics_csv is not None:
        print(f"Metrics CSV:  {metrics_csv.resolve()}")
    else:
        print("Metrics CSV:  skipped")
    if plot_paths:
        for name, p in plot_paths.items():
            print(f"Plot ({name}): {p.resolve()}")
    else:
        print("Plots:        skipped")
    print(f"Summary:      {summary_path.resolve()}")
    # END
