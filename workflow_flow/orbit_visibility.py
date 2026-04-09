import math

import numpy as np

from leo_kepler_rotation import run_leo_orbit_rotation_task

EARTH_RADIUS_M = 6_371_000.0
SPEED_OF_LIGHT_MPS = 299_792_458.0


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


def check_satellite_visibility(visibility_info: dict):
    windows = visibility_info["windows"]
    if not windows:
        return False, None
    first_window = windows[0]
    selected_frame = (first_window[0] + first_window[1]) // 2
    return True, int(selected_frame)


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
