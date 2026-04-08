import json
import math
import random
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from demodulator_power import DemodulatorPowerModel
from export import export_metrics, generate_performance_plots
from coverage_population import export_coverage_population_csv
from leo_kepler_rotation import run_leo_orbit_rotation_task
from lrfhss_connector import load_lrfhss_components
from multi_beam_connector import load_multi_beam_modules

EARTH_RADIUS_M = 6_371_000.0
SPEED_OF_LIGHT_MPS = 299_792_458.0
DEMOD_POWER_MODEL = DemodulatorPowerModel()


def compute_generated_power_w(
    sunlit: bool,
    panel_area_m2: float,
    solar_irradiance_w_m2: float,
    panel_efficiency: float,
    power_conditioning_efficiency: float,
) -> float:
    if not sunlit:
        return 0.0
    panel_raw_w = float(panel_area_m2 * solar_irradiance_w_m2 * panel_efficiency)
    return float(panel_raw_w * power_conditioning_efficiency)


def compute_power_balance(
    generated_power_w: float,
    power_consumption_watts: float,
    battery_percent: float,
    battery_max_charge_w: float,
) -> tuple[bool, float, float, float]:
    surplus_watts = float(generated_power_w - power_consumption_watts)

    if battery_percent >= 99.0:
        charge_acceptance_scale = 0.0
    elif battery_percent >= 95.0:
        charge_acceptance_scale = 0.25
    elif battery_percent >= 90.0:
        charge_acceptance_scale = 0.5
    else:
        charge_acceptance_scale = 1.0

    max_charge_watts = float(battery_max_charge_w * charge_acceptance_scale)
    charging_power_watts = float(min(max(surplus_watts, 0.0), max_charge_watts))
    discharging_power_watts = float(max(-surplus_watts, 0.0))
    net_power_watts = float(charging_power_watts - discharging_power_watts)
    charging = bool(net_power_watts > 0.0)
    return charging, charging_power_watts, discharging_power_watts, net_power_watts


def update_battery_percentage(
    battery_percent: float,
    net_power_watts: float,
    step_seconds: float,
    battery_capacity_wh: float,
    battery_charge_efficiency: float,
    battery_discharge_efficiency: float,
) -> float:
    step_hours = float(step_seconds / 3600.0)
    delta_wh = float(net_power_watts * step_hours)
    if delta_wh >= 0.0:
        delta_wh *= battery_charge_efficiency
    else:
        delta_wh /= max(battery_discharge_efficiency, 1e-9)
    delta_percent = float((delta_wh / battery_capacity_wh) * 100.0)
    new_pct = float(battery_percent + delta_percent)
    return float(max(0.0, min(100.0, new_pct)))


def compute_power_consumption(
    visible: bool,
    allocated_demods: int,
    tx_count: int,
    demod_tx_capacity_per_step: float,
    base_power_w: float,
    rf_frontend_power_w: float,
) -> tuple[float, float, float]:
    demod_result = DEMOD_POWER_MODEL.evaluate(
        visible=visible,
        allocated_demods=allocated_demods,
        tx_count=tx_count,
        demod_tx_capacity_per_step=demod_tx_capacity_per_step,
    )
    total_w = float(base_power_w + rf_frontend_power_w + demod_result.total_demod_power_w)
    return total_w, demod_result.mean_demod_power_w, demod_result.utilization


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
    battery_initial_percent: float
    low_battery_threshold: float
    idle_battery_threshold: float
    high_charge_threshold: float
    scenario_steps: int
    step_seconds: float
    panel_area_m2: float
    solar_irradiance_w_m2: float
    panel_efficiency: float
    power_conditioning_efficiency: float
    battery_capacity_wh: float
    battery_max_charge_w: float
    battery_charge_efficiency: float
    battery_discharge_efficiency: float
    demod_tx_capacity_per_step: float
    base_power_w: float
    rf_frontend_power_w: float
    min_demod_allocation: int
    max_demod_step_change: int
    policy_labels: list[str]
    lrfhss_spreading_label: str
    lrfhss_coding_rate: str
    lrfhss_fragmentation_fragments: int
    lrfhss_payload_bytes: int
    center_frequency_hz: float
    noise_bandwidth_hz: float
    tx_power_dbm: float
    tx_gain_dbi: float
    rx_gain_dbi: float
    implementation_loss_db: float
    noise_figure_db: float


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
    battery_initial_percent: float,
    low_battery_threshold: float,
    idle_battery_threshold: float,
    high_charge_threshold: float,
    runs_per_point: int,
    scenario_steps: int,
    step_seconds: float,
    panel_area_m2: float,
    solar_irradiance_w_m2: float,
    panel_efficiency: float,
    power_conditioning_efficiency: float,
    battery_capacity_wh: float,
    battery_max_charge_w: float,
    battery_charge_efficiency: float,
    battery_discharge_efficiency: float,
    demod_tx_capacity_per_step: float,
    base_power_w: float,
    rf_frontend_power_w: float,
    min_demod_allocation: int,
    max_demod_step_change: int,
) -> PipelineConfig:
    if nodes_list:
        loads = sorted(set(int(v) for v in nodes_list if int(v) >= 0))
    else:
        loads = [int(round(v)) for v in np.logspace(np.log10(node_min), np.log10(node_max), num=node_points)]
        loads = sorted(set(loads))
    return PipelineConfig(
        node_loads=loads,
        demodulator_options=demodulator_options,
        runs_per_point=max(1, int(runs_per_point)),
        visibility_min_elev_deg=10.0,
        output_dir=output_dir,
        seed=seed,
        export_csv=export_csv,
        generate_plots=generate_plots,
        battery_initial_percent=battery_initial_percent,
        low_battery_threshold=low_battery_threshold,
        idle_battery_threshold=idle_battery_threshold,
        high_charge_threshold=high_charge_threshold,
        scenario_steps=max(1, int(scenario_steps)),
        step_seconds=float(step_seconds),
        panel_area_m2=float(panel_area_m2),
        solar_irradiance_w_m2=float(solar_irradiance_w_m2),
        panel_efficiency=float(panel_efficiency),
        power_conditioning_efficiency=float(power_conditioning_efficiency),
        battery_capacity_wh=float(battery_capacity_wh),
        battery_max_charge_w=float(battery_max_charge_w),
        battery_charge_efficiency=float(battery_charge_efficiency),
        battery_discharge_efficiency=float(battery_discharge_efficiency),
        demod_tx_capacity_per_step=float(demod_tx_capacity_per_step),
        base_power_w=float(base_power_w),
        rf_frontend_power_w=float(rf_frontend_power_w),
        min_demod_allocation=max(0, int(min_demod_allocation)),
        max_demod_step_change=max(1, int(max_demod_step_change)),
        policy_labels=["EnergyAware", "NonEnergyAware"],
        lrfhss_spreading_label="LR-FHSS (grid-hopping)",
        lrfhss_coding_rate="1/3",
        lrfhss_fragmentation_fragments=6,
        lrfhss_payload_bytes=15,
        center_frequency_hz=868_000_000.0,
        noise_bandwidth_hz=488.0,
        tx_power_dbm=14.0,
        tx_gain_dbi=0.0,
        rx_gain_dbi=2.0,
        implementation_loss_db=2.0,
        noise_figure_db=5.0,
    )

def compute_satellite_orbit(network_geometry, params_mod, step_seconds: float, scenario_steps: int):
    del network_geometry
    params_config = None
    if params_mod is not None and hasattr(params_mod, "read_params"):
        params_config = params_mod.read_params()

    orbit_state = run_leo_orbit_rotation_task(
        params_config=params_config,
        fallback_step_s=step_seconds,
        minimum_frames=max(720, int(scenario_steps) * 10),
    )
    return orbit_state["satellite_positions_m"], orbit_state


def _extract_windows(mask: np.ndarray) -> list[tuple[int, int]]:
    windows: list[tuple[int, int]] = []
    start = None
    for i, flag in enumerate(mask):
        if bool(flag) and start is None:
            start = i
        if (not bool(flag)) and start is not None:
            windows.append((start, i - 1))
            start = None
    if start is not None:
        windows.append((start, len(mask) - 1))
    return windows


def generate_visibility_windows(sat_pos: np.ndarray, utils_mod, min_elev_deg: float):
    elev_deg = utils_mod.get_elevation_angle_from_center(sat_pos[0, :], sat_pos[2, :]) * 180.0 / np.pi
    visible = elev_deg >= min_elev_deg
    windows = _extract_windows(visible)
    return {
        "visible_mask": visible,
        "elevation_deg": elev_deg,
        "windows": windows,
        "visible_ratio": float(np.mean(visible.astype(float))),
    }


def generate_sunlight_windows(sat_pos: np.ndarray):
    sunlit_mask = sat_pos[0, :] >= 0.0
    sunlit_windows = _extract_windows(sunlit_mask)
    eclipse_windows = _extract_windows(~sunlit_mask)
    return {
        "sunlit_mask": sunlit_mask,
        "sunlit_windows": sunlit_windows,
        "eclipse_windows": eclipse_windows,
        "sunlit_ratio": float(np.mean(sunlit_mask.astype(float))),
        "eclipse_ratio": float(np.mean((~sunlit_mask).astype(float))),
    }


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


def transmit_fragments(packet_count: int, visible: bool):
    return packet_count if visible else 0


def detect_collisions(decoded_metrics: dict):
    return int(decoded_metrics["collided"])


def baseline_packet_decoding(LoRaNetwork, node_count: int, demods: int, use_earlydecode: bool, use_earlydrop: bool):
    if node_count <= 0 or demods <= 0:
        return {
            "tracked_txs": 0,
            "decoded_headers": 0,
            "decoded_header_payloads": 0,
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
        "decoded_headers": int(network.get_decoded_hdr()),
        "decoded_header_payloads": int(network.get_decoded_hrd_pld()),
        "decoded_bytes": int(network.get_decoded_bytes()),
        "collided": int(network.get_collided_hdr_pld()),
    }


def allocate_demodulators(
    policy_label: str,
    requested_demods: int,
    visible: bool,
    battery_percent: float,
    idle_battery_threshold: float,
    min_demod_allocation: int,
    max_demod_step_change: int,
    previous_allocated_demods: int,
) -> int:
    if (not visible) or requested_demods <= 0:
        return 0

    if policy_label == "NonEnergyAware":
        target = int(requested_demods)
    else:
        if battery_percent < idle_battery_threshold:
            target = max(min_demod_allocation, int(round(requested_demods * 0.35)))
        elif battery_percent < 60.0:
            target = max(min_demod_allocation, int(round(requested_demods * 0.60)))
        elif battery_percent < 80.0:
            target = max(min_demod_allocation, int(round(requested_demods * 0.80)))
        else:
            target = int(requested_demods)

    delta = target - previous_allocated_demods
    if abs(delta) > max_demod_step_change:
        target = previous_allocated_demods + int(np.sign(delta) * max_demod_step_change)
    return int(max(0, min(requested_demods, target)))


def summarize_stats(values: list[float]) -> dict:
    arr = np.array(values, dtype=float)
    if arr.size == 0:
        return {"mean": 0.0, "variance": 0.0, "ci95_low": 0.0, "ci95_high": 0.0}
    mean_val = float(np.mean(arr))
    variance_val = float(np.var(arr, ddof=1)) if arr.size > 1 else 0.0
    std_val = float(np.std(arr, ddof=1)) if arr.size > 1 else 0.0
    ci_half = float(1.96 * std_val / math.sqrt(arr.size)) if arr.size > 1 else 0.0
    return {
        "mean": mean_val,
        "variance": variance_val,
        "ci95_low": float(mean_val - ci_half),
        "ci95_high": float(mean_val + ci_half),
    }


def compute_link_budget_and_doppler(
    sat_pos: np.ndarray,
    selected_frame: int,
    step_seconds: float,
    center_frequency_hz: float,
    noise_bandwidth_hz: float,
    tx_power_dbm: float,
    tx_gain_dbi: float,
    rx_gain_dbi: float,
    implementation_loss_db: float,
    noise_figure_db: float,
) -> dict:
    frame = int(max(0, min(selected_frame, sat_pos.shape[1] - 1)))
    sat_xyz = sat_pos[:, frame]
    sat_radius_m = float(np.linalg.norm(sat_xyz))
    altitude_m = float(max(1.0, sat_radius_m - EARTH_RADIUS_M))
    slant_range_km = float(altitude_m / 1000.0)
    f_ghz = float(center_frequency_hz / 1e9)
    free_space_path_loss_db = float(92.45 + 20.0 * math.log10(max(f_ghz, 1e-9)) + 20.0 * math.log10(max(slant_range_km, 1e-9)))
    rx_power_dbm = float(tx_power_dbm + tx_gain_dbi + rx_gain_dbi - free_space_path_loss_db - implementation_loss_db)
    noise_floor_dbm = float(-174.0 + 10.0 * math.log10(max(noise_bandwidth_hz, 1e-9)) + noise_figure_db)
    snr_db = float(rx_power_dbm - noise_floor_dbm)

    next_frame = (frame + 1) % sat_pos.shape[1]
    prev_frame = (frame - 1) % sat_pos.shape[1]
    velocity_vec = (sat_pos[:, next_frame] - sat_pos[:, prev_frame]) / (2.0 * step_seconds)
    radial_speed_mps = float(np.dot(velocity_vec, sat_xyz) / max(np.linalg.norm(sat_xyz), 1e-9))
    doppler_hz = float((radial_speed_mps / SPEED_OF_LIGHT_MPS) * center_frequency_hz)

    return {
        "slant_range_km": slant_range_km,
        "free_space_path_loss_db": free_space_path_loss_db,
        "rx_power_dbm": rx_power_dbm,
        "noise_floor_dbm": noise_floor_dbm,
        "snr_db": snr_db,
        "doppler_hz": doppler_hz,
    }


def compute_orbit_parameters(sat_pos: np.ndarray, step_seconds: float) -> dict:
    radii = np.linalg.norm(sat_pos, axis=0)
    altitudes_km = (radii - EARTH_RADIUS_M) / 1000.0
    altitude_km = float(np.mean(altitudes_km))

    vel = np.diff(sat_pos, axis=1) / step_seconds
    speed_km_s = float(np.mean(np.linalg.norm(vel, axis=0)) / 1000.0) if vel.shape[1] > 0 else 0.0

    if sat_pos.shape[1] >= 2:
        h_vec = np.cross(sat_pos[:, 0], sat_pos[:, 1])
        h_norm = float(np.linalg.norm(h_vec))
        if h_norm > 0.0:
            inclination_deg = float(np.degrees(np.arccos(max(-1.0, min(1.0, h_vec[2] / h_norm)))))
        else:
            inclination_deg = 0.0
    else:
        inclination_deg = 0.0

    return {
        "altitude_km": altitude_km,
        "inclination_deg": inclination_deg,
        "mean_orbital_speed_km_s": speed_km_s,
    }

def simulate_power_policy(
    cfg: PipelineConfig,
    nodes: int,
    requested_demods: int,
    packet_count: int,
    selected_frame: int,
    visibility_mask: np.ndarray,
    policy_label: str,
) -> dict:
    del nodes
    allocated_demods = int(requested_demods)
    frame_count = len(visibility_mask)

    allocated_trace = []
    power_trace_w = []
    utilization_trace = []
    tx_trace = []
    visible_trace = []
    terminal_demod_power_w = 0.0

    for step in range(cfg.scenario_steps):
        frame = (selected_frame + step) % frame_count
        visible = bool(visibility_mask[frame])
        tx_count = int(transmit_fragments(packet_count=packet_count, visible=visible))

        allocated_demods = allocate_demodulators(
            policy_label=policy_label,
            requested_demods=requested_demods,
            visible=visible,
            battery_percent=100.0,
            idle_battery_threshold=cfg.idle_battery_threshold,
            min_demod_allocation=cfg.min_demod_allocation,
            max_demod_step_change=cfg.max_demod_step_change,
            previous_allocated_demods=allocated_demods,
        )
        power_consumption_w, demod_power_w, utilization = compute_power_consumption(
            visible=visible,
            allocated_demods=allocated_demods,
            tx_count=tx_count,
            demod_tx_capacity_per_step=cfg.demod_tx_capacity_per_step,
            base_power_w=cfg.base_power_w,
            rf_frontend_power_w=cfg.rf_frontend_power_w,
        )
        terminal_demod_power_w = demod_power_w
        allocated_trace.append(float(allocated_demods))
        power_trace_w.append(float(power_consumption_w))
        utilization_trace.append(float(utilization))
        tx_trace.append(float(tx_count))
        visible_trace.append(1.0 if visible else 0.0)

    return {
        "policy_label": policy_label,
        "mean_allocated_demods": float(np.mean(allocated_trace)),
        "mean_power_consumption_watts": float(np.mean(power_trace_w)),
        "mean_demod_utilization": float(np.mean(utilization_trace)),
        "mean_tx_count_per_step": float(np.mean(tx_trace)),
        "visibility_ratio": float(np.mean(visible_trace)),
        "terminal_allocated_demods": int(round(allocated_trace[-1])),
        "terminal_demod_power_watts": float(terminal_demod_power_w),
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
