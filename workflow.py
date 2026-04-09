import json
import random
from pathlib import Path

import numpy as np

from coverage_population import export_coverage_population_csv
from export import export_metrics, generate_performance_plots
from lrfhss_connector import load_lrfhss_components
from multi_beam_connector import load_multi_beam_modules
from workflow_flow.config import initialize_simulation_parameters
from workflow_flow.lrfhss_baseline import (
    assign_lrfhss_packets,
    baseline_packet_decoding,
    detect_collisions,
    generate_iot_nodes,
    summarize_stats,
)
from workflow_flow.orbit_visibility import (
    check_satellite_visibility,
    compute_link_budget_and_doppler,
    compute_orbit_parameters,
    compute_satellite_orbit,
    generate_visibility_windows,
)
from workflow_flow.power_policy import simulate_power_policy

__all__ = ["run_workflow"]


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
    battery_initial_percent: float,
    battery_decay_per_w: float,
    charging_rate_per_step: float,
    low_battery_threshold: float,
    idle_battery_threshold: float,
    high_charge_threshold: float,
    runs_per_point: int = 50,
    scenario_steps: int = 120,
    step_seconds: float = 228.0,
    panel_area_m2: float = 0.40,
    solar_irradiance_w_m2: float = 950.0,
    panel_efficiency: float = 0.20,
    power_conditioning_efficiency: float = 0.90,
    battery_capacity_wh: float = 220.0,
    battery_max_charge_w: float = 80.0,
    battery_charge_efficiency: float = 0.95,
    battery_discharge_efficiency: float = 0.95,
    demod_tx_capacity_per_step: float = 8.0,
    base_power_w: float = 5.0,
    rf_frontend_power_w: float = 1.8,
    min_demod_allocation: int = 5,
    max_demod_step_change: int = 80,
):
    del battery_decay_per_w, charging_rate_per_step
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
        battery_initial_percent=battery_initial_percent,
        low_battery_threshold=low_battery_threshold,
        idle_battery_threshold=idle_battery_threshold,
        high_charge_threshold=high_charge_threshold,
        runs_per_point=runs_per_point,
        scenario_steps=scenario_steps,
        step_seconds=step_seconds,
        panel_area_m2=panel_area_m2,
        solar_irradiance_w_m2=solar_irradiance_w_m2,
        panel_efficiency=panel_efficiency,
        power_conditioning_efficiency=power_conditioning_efficiency,
        battery_capacity_wh=battery_capacity_wh,
        battery_max_charge_w=battery_max_charge_w,
        battery_charge_efficiency=battery_charge_efficiency,
        battery_discharge_efficiency=battery_discharge_efficiency,
        demod_tx_capacity_per_step=demod_tx_capacity_per_step,
        base_power_w=base_power_w,
        rf_frontend_power_w=rf_frontend_power_w,
        min_demod_allocation=min_demod_allocation,
        max_demod_step_change=max_demod_step_change,
    )

    _, network_geometry, params_mod, utils_mod = load_multi_beam_modules(multi_beam_root)
    LoRaNetwork = load_lrfhss_components(lrfhss_root)

    random.seed(cfg.seed)
    np.random.seed(cfg.seed)

    sat_pos, orbit_task_info = compute_satellite_orbit(
        network_geometry=network_geometry,
        params_mod=params_mod,
        step_seconds=cfg.step_seconds,
        scenario_steps=cfg.scenario_steps,
    )
    visibility_info = generate_visibility_windows(sat_pos, utils_mod, cfg.visibility_min_elev_deg)
    params_config = params_mod.read_params() if params_mod is not None and hasattr(params_mod, "read_params") else {}
    coverage_csv_path = cfg.output_dir.parent / "csv" / "coverage_population_devices.csv"
    coverage_trace_csv_path = cfg.output_dir.parent / "csv" / "coverage_track_trace.csv"
    ground_track_lat = orbit_task_info.get("satellite_ground_track_lat_deg")
    ground_track_lon = orbit_task_info.get("satellite_ground_track_lon_deg")
    coverage_info = export_coverage_population_csv(
        input_csv=Path("Data") / "adult_population_country_coordinates.csv",
        output_csv=coverage_csv_path,
        params_config=params_config,
        ground_track_lat_deg=np.array(ground_track_lat, copy=True) if ground_track_lat is not None else None,
        ground_track_lon_deg=np.array(ground_track_lon, copy=True) if ground_track_lon is not None else None,
        max_ground_track_points=2000,
        trace_csv=coverage_trace_csv_path,
        print_track_changes=True,
        device_penetration_ratio=0.001,
        devices_per_demodulator=250,
    )
    orbit_parameters = compute_orbit_parameters(
        sat_pos=sat_pos,
        step_seconds=orbit_task_info["orbit_task"]["orbit_config"]["time_step_s"],
    )
    global_visible, selected_frame = check_satellite_visibility(visibility_info)
    selected_frame_for_link = int(selected_frame) if selected_frame is not None else 0
    link_budget = compute_link_budget_and_doppler(
        sat_pos=sat_pos,
        selected_frame=selected_frame_for_link,
        step_seconds=cfg.step_seconds,
        center_frequency_hz=cfg.center_frequency_hz,
        noise_bandwidth_hz=cfg.noise_bandwidth_hz,
        tx_power_dbm=cfg.tx_power_dbm,
        tx_gain_dbi=cfg.tx_gain_dbi,
        rx_gain_dbi=cfg.rx_gain_dbi,
        implementation_loss_db=cfg.implementation_loss_db,
        noise_figure_db=cfg.noise_figure_db,
    )

    all_records = []

    for nodes in cfg.node_loads:
        iot_nodes = generate_iot_nodes(nodes)
        packet_count = assign_lrfhss_packets(iot_nodes)

        for requested_demods in cfg.demodulator_options:
            for policy_label in cfg.policy_labels:
                power_sim = simulate_power_policy(
                    cfg=cfg,
                    nodes=nodes,
                    requested_demods=requested_demods,
                    packet_count=packet_count,
                    selected_frame=selected_frame_for_link,
                    visibility_mask=visibility_info["visible_mask"],
                    policy_label=policy_label,
                )
                representative_demods = int(round(power_sim["mean_allocated_demods"]))
                representative_tx = int(round(power_sim["mean_tx_count_per_step"]))
                representative_visible = bool(power_sim["visibility_ratio"] > 0.0 and global_visible)

                decoded_header_runs = []
                decoded_header_payload_runs = []
                tracked_runs = []
                decoded_bytes_runs = []
                collision_runs = []
                throughput_bps_runs = []
                energy_per_decoded_bit_j_runs = []
                decoding_efficiency_runs = []

                for run_idx in range(cfg.runs_per_point):
                    seed_run = (
                        cfg.seed
                        + int(nodes) * 100_000
                        + int(requested_demods) * 1_000
                        + int(run_idx)
                        + (0 if policy_label == "EnergyAware" else 500_000_000)
                    )
                    random.seed(seed_run)
                    decode_metrics = baseline_packet_decoding(
                        LoRaNetwork=LoRaNetwork,
                        node_count=representative_tx,
                        demods=representative_demods,
                        use_earlydecode=False,
                        use_earlydrop=False,
                    )
                    tracked = float(decode_metrics["tracked_txs"])
                    decoded_headers = float(decode_metrics["decoded_headers"])
                    decoded_header_payloads = float(decode_metrics["decoded_header_payloads"])
                    decoded_bytes = float(decode_metrics["decoded_bytes"])
                    collided = float(detect_collisions(decode_metrics))

                    throughput_bps = float((decoded_bytes * 8.0) / max(cfg.step_seconds, 1e-9))
                    decoded_bits = max(decoded_bytes * 8.0, 1.0)
                    energy_per_decoded_bit_j = float((power_sim["mean_power_consumption_watts"] * cfg.step_seconds) / decoded_bits)
                    decoding_efficiency = float(decoded_header_payloads / max(tracked, 1.0))

                    tracked_runs.append(tracked)
                    decoded_header_runs.append(decoded_headers)
                    decoded_header_payload_runs.append(decoded_header_payloads)
                    decoded_bytes_runs.append(decoded_bytes)
                    collision_runs.append(collided)
                    throughput_bps_runs.append(throughput_bps)
                    energy_per_decoded_bit_j_runs.append(energy_per_decoded_bit_j)
                    decoding_efficiency_runs.append(decoding_efficiency)

                decoded_headers_stats = summarize_stats(decoded_header_runs)
                decoded_header_payloads_stats = summarize_stats(decoded_header_payload_runs)
                tracked_stats = summarize_stats(tracked_runs)
                decoded_bytes_stats = summarize_stats(decoded_bytes_runs)
                collisions_stats = summarize_stats(collision_runs)
                throughput_stats = summarize_stats(throughput_bps_runs)
                energy_per_bit_stats = summarize_stats(energy_per_decoded_bit_j_runs)
                decoding_efficiency_stats = summarize_stats(decoding_efficiency_runs)

                all_records.append(
                    {
                        "nodes": int(nodes),
                        "policy_label": policy_label,
                        "visible": representative_visible,
                        "selected_frame": selected_frame_for_link,
                        "requested_demods": int(requested_demods),
                        "allocated_demods": int(representative_demods),
                        "power_consumption_watts": float(power_sim["mean_power_consumption_watts"]),
                        "mode_label": "Baseline",
                        "decoded_headers": decoded_headers_stats["mean"],
                        "decoded_headers_variance": decoded_headers_stats["variance"],
                        "decoded_headers_ci95_low": decoded_headers_stats["ci95_low"],
                        "decoded_headers_ci95_high": decoded_headers_stats["ci95_high"],
                        "decoded_header_payloads": decoded_header_payloads_stats["mean"],
                        "decoded_header_payloads_variance": decoded_header_payloads_stats["variance"],
                        "decoded_header_payloads_ci95_low": decoded_header_payloads_stats["ci95_low"],
                        "decoded_header_payloads_ci95_high": decoded_header_payloads_stats["ci95_high"],
                        "decoded_headers_including_payloads": float(
                            decoded_headers_stats["mean"] + decoded_header_payloads_stats["mean"]
                        ),
                        "tracked_txs": tracked_stats["mean"],
                        "tracked_txs_variance": tracked_stats["variance"],
                        "decoded_bytes": decoded_bytes_stats["mean"],
                        "decoded_bytes_variance": decoded_bytes_stats["variance"],
                        "collided": collisions_stats["mean"],
                        "collided_variance": collisions_stats["variance"],
                        "throughput_bps": throughput_stats["mean"],
                        "throughput_bps_variance": throughput_stats["variance"],
                        "throughput_bps_ci95_low": throughput_stats["ci95_low"],
                        "throughput_bps_ci95_high": throughput_stats["ci95_high"],
                        "energy_per_decoded_bit_j": energy_per_bit_stats["mean"],
                        "energy_per_decoded_bit_j_variance": energy_per_bit_stats["variance"],
                        "decoding_efficiency": decoding_efficiency_stats["mean"],
                        "decoding_efficiency_variance": decoding_efficiency_stats["variance"],
                        "monte_carlo_runs": int(cfg.runs_per_point),
                        "seed_base": int(cfg.seed),
                        "seed_formula": "seed_base + nodes*100000 + demods*1000 + run_idx + policy_offset",
                        "scenario_steps": int(cfg.scenario_steps),
                        "time_step_seconds": float(cfg.step_seconds),
                    }
                )

    metrics_json, metrics_csv = export_metrics(all_records, cfg.output_dir, cfg.export_csv)
    plot_paths = generate_performance_plots(all_records, cfg.output_dir) if cfg.generate_plots else {}

    summary = {
        "workflow": [
            "START",
            "Initialize simulation parameters",
            "Check LEO orbit config or use default, then propagate Kepler rotation",
            "Check Earth coverage areas (lat/lon) and estimate devices/demodulators",
            "Generate visibility windows",
            "Generate IoT nodes and packets",
            "Apply policy-based demodulator allocation",
            "Run LR-FHSS baseline decoding",
            "Compute power consumption",
            "Monte Carlo aggregation (mean/variance/CI95)",
            "Generate performance plots",
            "END",
        ],
        "dimensions_and_units": {
            "power": "W",
            "time_step": "s",
            "throughput": "bps",
            "doppler": "Hz",
            "path_loss": "dB",
            "snr": "dB",
        },
        "assumptions": [
            "power model excludes generation/storage dynamics",
            "fixed LR-FHSS profile per run (no adaptive coding)",
        ],
        "demodulator_definition": "Digital LR-FHSS decoding core allocation (hardware accelerator abstraction).",
        "power_model": {
            "equation": "P_total = P_circuit + N_idle*P_idle + N_busy*P_busy",
            "P_circuit_w": float(cfg.base_power_w + cfg.rf_frontend_power_w),
            "P_base_w": cfg.base_power_w,
            "P_RF_w": cfg.rf_frontend_power_w,
            "demod_tx_capacity_per_step": cfg.demod_tx_capacity_per_step,
        },
        "visibility_model": {
            "elevation_threshold_deg": cfg.visibility_min_elev_deg,
            "visible_ratio": visibility_info["visible_ratio"],
            "visibility_windows": visibility_info["windows"],
        },
        "coverage_model": coverage_info,
        "orbit_task": orbit_task_info["orbit_task"],
        "orbit_parameters": orbit_parameters,
        "communication_model": {
            "lrfhss_spreading": cfg.lrfhss_spreading_label,
            "lrfhss_coding_rate": cfg.lrfhss_coding_rate,
            "lrfhss_fragmentation_fragments": cfg.lrfhss_fragmentation_fragments,
            "lrfhss_payload_bytes": cfg.lrfhss_payload_bytes,
            "center_frequency_hz": cfg.center_frequency_hz,
            "noise_bandwidth_hz": cfg.noise_bandwidth_hz,
            "tx_power_dbm": cfg.tx_power_dbm,
            "tx_gain_dbi": cfg.tx_gain_dbi,
            "rx_gain_dbi": cfg.rx_gain_dbi,
            "implementation_loss_db": cfg.implementation_loss_db,
            "noise_figure_db": cfg.noise_figure_db,
            "link_budget_at_selected_frame": link_budget,
        },
        "policies_compared": cfg.policy_labels,
        "monte_carlo_runs_per_point": cfg.runs_per_point,
        "scenario_steps": cfg.scenario_steps,
        "node_range": {"min": node_min, "max": node_max, "points": node_points},
        "metrics_json": str(metrics_json.resolve()),
        "metrics_csv": str(metrics_csv.resolve()) if metrics_csv else None,
        "plots": {k: str(v.resolve()) for k, v in plot_paths.items()},
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
