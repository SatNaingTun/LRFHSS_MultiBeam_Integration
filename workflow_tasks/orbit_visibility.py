import numpy as np

from leo_kepler_rotation import run_leo_orbit_rotation_task
from orbit_formula import (
    compute_doppler_shift_hz,
    compute_free_space_path_loss_db,
    compute_inclination_deg_from_positions,
    compute_mean_altitude_km,
    compute_mean_speed_km_s,
    compute_noise_floor_dbm,
    extract_windows,
)

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


def generate_visibility_windows(sat_pos: np.ndarray, utils_mod, min_elev_deg: float):
    elev_deg = utils_mod.get_elevation_angle_from_center(sat_pos[0, :], sat_pos[2, :]) * 180.0 / np.pi
    visible = elev_deg >= min_elev_deg
    windows = extract_windows(visible)
    return {
        "visible_mask": visible,
        "elevation_deg": elev_deg,
        "windows": windows,
        "visible_ratio": float(np.mean(visible.astype(float))),
    }


def generate_sunlight_windows(sat_pos: np.ndarray):
    sunlit_mask = sat_pos[0, :] >= 0.0
    sunlit_windows = extract_windows(sunlit_mask)
    eclipse_windows = extract_windows(~sunlit_mask)
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
    free_space_path_loss_db = compute_free_space_path_loss_db(
        center_frequency_hz=center_frequency_hz,
        slant_range_km=slant_range_km,
    )
    rx_power_dbm = float(tx_power_dbm + tx_gain_dbi + rx_gain_dbi - free_space_path_loss_db - implementation_loss_db)
    noise_floor_dbm = compute_noise_floor_dbm(
        noise_bandwidth_hz=noise_bandwidth_hz,
        noise_figure_db=noise_figure_db,
    )
    snr_db = float(rx_power_dbm - noise_floor_dbm)

    next_frame = (frame + 1) % sat_pos.shape[1]
    prev_frame = (frame - 1) % sat_pos.shape[1]
    velocity_vec = (sat_pos[:, next_frame] - sat_pos[:, prev_frame]) / (2.0 * step_seconds)
    radial_speed_mps = float(np.dot(velocity_vec, sat_xyz) / max(np.linalg.norm(sat_xyz), 1e-9))
    doppler_hz = compute_doppler_shift_hz(
        radial_speed_mps=radial_speed_mps,
        center_frequency_hz=center_frequency_hz,
        speed_of_light_mps=SPEED_OF_LIGHT_MPS,
    )

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
    altitude_km = compute_mean_altitude_km(radii_m=radii, earth_radius_m=EARTH_RADIUS_M)
    speed_km_s = compute_mean_speed_km_s(positions_m=sat_pos, step_seconds=step_seconds)
    inclination_deg = compute_inclination_deg_from_positions(sat_pos=sat_pos)

    return {
        "altitude_km": altitude_km,
        "inclination_deg": inclination_deg,
        "mean_orbital_speed_km_s": speed_km_s,
    }
