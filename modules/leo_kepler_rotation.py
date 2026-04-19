from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
from modules.orbit_formula import (
    compute_mean_anomaly_rad,
    compute_perifocal_state_vectors,
    compute_pqw_to_eci_dcm,
    compute_horizon_visibility_span_seconds,
    compute_mean_motion_rad_s,
    compute_orbital_period_s,
    compute_semi_major_axis_m,
    solve_kepler_equation,
    safe_float,
    normalize_columns,
    wrap_longitude_deg,
)

# Citable algorithms used in this module:
# 1) Two-body Keplerian propagation from classical orbital elements.
# 2) Newton-Raphson solution of Kepler's equation: M = E - e*sin(E).
# References:
# - D. A. Vallado, Fundamentals of Astrodynamics and Applications, 4th ed.
# - H. D. Curtis, Orbital Mechanics for Engineering Students, 4th ed.

EARTH_MU_M3_S2 = 3.986004418e14
EARTH_RADIUS_M = 6_371_000.0
EARTH_ROTATION_RAD_S = 7.2921159e-5


@dataclass(frozen=True)
class LEOOrbitConfig:
    altitude_m: float = 600_000.0
    eccentricity: float = 0.001
    inclination_deg: float = 86.4
    raan_deg: float = 0.0
    arg_perigee_deg: float = 0.0
    mean_anomaly_epoch_deg: float = 0.0
    earth_mu_m3_s2: float = EARTH_MU_M3_S2
    earth_radius_m: float = EARTH_RADIUS_M
    time_step_s: float = 1.0

    @property
    def semi_major_axis_m(self) -> float:
        return compute_semi_major_axis_m(earth_radius_m=self.earth_radius_m, altitude_m=self.altitude_m)

    @property
    def mean_motion_rad_s(self) -> float:
        return compute_mean_motion_rad_s(
            earth_mu_m3_s2=self.earth_mu_m3_s2,
            semi_major_axis_m=self.semi_major_axis_m,
        )

    @property
    def orbital_period_s(self) -> float:
        return compute_orbital_period_s(mean_motion_rad_s=self.mean_motion_rad_s)


def build_leo_orbit_config(
    params_config: Mapping[str, Any] | None,
    fallback_step_s: float,
) -> tuple[LEOOrbitConfig, dict[str, Any]]:
    defaults = LEOOrbitConfig(time_step_s=max(1e-3, float(fallback_step_s)))

    if not params_config:
        return defaults, {
            "source": "default",
            "used_default": True,
            "reason": "orbit config missing",
        }

    earth_radius_m = safe_float(params_config.get("r_earth"), defaults.earth_radius_m)
    altitude_m = safe_float(params_config.get("h_satellite"), defaults.altitude_m)
    time_step_s = safe_float(params_config.get("t_frame"), defaults.time_step_s)

    leo_min_alt_m = 160_000.0
    leo_max_alt_m = 2_000_000.0
    used_default = False
    reasons: list[str] = []

    if not (leo_min_alt_m <= altitude_m <= leo_max_alt_m):
        altitude_m = defaults.altitude_m
        used_default = True
        reasons.append("h_satellite outside LEO range; fallback default")

    if earth_radius_m <= 0.0:
        earth_radius_m = defaults.earth_radius_m
        used_default = True
        reasons.append("invalid r_earth; fallback default")

    if time_step_s <= 0.0:
        time_step_s = defaults.time_step_s
        used_default = True
        reasons.append("invalid t_frame; fallback default")

    # Optional advanced orbital elements with safe defaults.
    eccentricity = safe_float(params_config.get("orbit_eccentricity"), defaults.eccentricity)
    inclination_deg = safe_float(params_config.get("orbit_inclination_deg"), defaults.inclination_deg)
    raan_deg = safe_float(params_config.get("orbit_raan_deg"), defaults.raan_deg)
    arg_perigee_deg = safe_float(params_config.get("orbit_arg_perigee_deg"), defaults.arg_perigee_deg)
    mean_anomaly_epoch_deg = safe_float(params_config.get("orbit_mean_anomaly_epoch_deg"), defaults.mean_anomaly_epoch_deg)

    if not (0.0 <= eccentricity < 1.0):
        eccentricity = defaults.eccentricity
        used_default = True
        reasons.append("invalid eccentricity; fallback default")

    cfg = LEOOrbitConfig(
        altitude_m=altitude_m,
        eccentricity=eccentricity,
        inclination_deg=inclination_deg,
        raan_deg=raan_deg,
        arg_perigee_deg=arg_perigee_deg,
        mean_anomaly_epoch_deg=mean_anomaly_epoch_deg,
        earth_radius_m=earth_radius_m,
        time_step_s=max(1e-3, time_step_s),
    )

    return cfg, {
        "source": "params.json",
        "used_default": bool(used_default),
        "reason": "; ".join(reasons) if reasons else "valid LEO config",
    }


def propagate_kepler_orbit_with_rotation(
    orbit_cfg: LEOOrbitConfig,
    frame_count: int,
) -> dict[str, Any]:
    n = int(max(8, frame_count))
    dt = float(orbit_cfg.time_step_s)

    half_span = (n - 1) // 2
    timestamps_s = (np.arange(n, dtype=float) - float(half_span)) * dt

    a = orbit_cfg.semi_major_axis_m
    e = float(orbit_cfg.eccentricity)
    mu = float(orbit_cfg.earth_mu_m3_s2)

    inc = math.radians(orbit_cfg.inclination_deg)
    raan = math.radians(orbit_cfg.raan_deg)
    argp = math.radians(orbit_cfg.arg_perigee_deg)
    m0 = math.radians(orbit_cfg.mean_anomaly_epoch_deg)

    mean_motion = orbit_cfg.mean_motion_rad_s
    mean_anomaly = compute_mean_anomaly_rad(
        m0_rad=m0,
        mean_motion_rad_s=mean_motion,
        timestamps_s=timestamps_s,
    )
    ecc_anomaly = solve_kepler_equation(mean_anomaly, e)

    # Perifocal state vectors (Curtis/Vallado) from centralized Kepler formulas.
    r_pqw, v_pqw = compute_perifocal_state_vectors(
        semi_major_axis_m=a,
        eccentricity=e,
        earth_mu_m3_s2=mu,
        eccentric_anomaly_rad=ecc_anomaly,
    )

    q_pqw_to_eci = compute_pqw_to_eci_dcm(
        raan_rad=raan,
        inclination_rad=inc,
        arg_perigee_rad=argp,
    )
    r_eci = q_pqw_to_eci @ r_pqw
    v_eci = q_pqw_to_eci @ v_pqw

    # Build local orbital frame using epoch sub-satellite direction as local +Z.
    center_idx = int(np.argmin(np.abs(timestamps_s)))
    r0 = r_eci[:, center_idx]
    v0 = v_eci[:, center_idx]

    z_axis = r0 / max(np.linalg.norm(r0), 1e-12)
    h_axis = np.cross(r0, v0)
    y_axis = h_axis / max(np.linalg.norm(h_axis), 1e-12)
    x_axis = np.cross(y_axis, z_axis)
    x_axis = x_axis / max(np.linalg.norm(x_axis), 1e-12)
    y_axis = np.cross(z_axis, x_axis)
    y_axis = y_axis / max(np.linalg.norm(y_axis), 1e-12)

    q_eci_to_local = np.vstack((x_axis, y_axis, z_axis))
    local_origin_eci = orbit_cfg.earth_radius_m * z_axis

    sat_local = q_eci_to_local @ (r_eci - local_origin_eci[:, None])
    vel_local = q_eci_to_local @ v_eci

    # Nadir-pointing body frame rotation per sample.
    sat_from_earth_center_local = sat_local.copy()
    sat_from_earth_center_local[2, :] += orbit_cfg.earth_radius_m
    radial_hat = normalize_columns(sat_from_earth_center_local)

    tangential = vel_local - radial_hat * np.sum(vel_local * radial_hat, axis=0, keepdims=True)
    x_body = normalize_columns(tangential)
    z_body = -radial_hat
    y_body = normalize_columns(np.cross(z_body.T, x_body.T).T)
    x_body = normalize_columns(np.cross(y_body.T, z_body.T).T)

    body_to_local = np.zeros((n, 3, 3), dtype=float)
    body_to_local[:, :, 0] = x_body.T
    body_to_local[:, :, 1] = y_body.T
    body_to_local[:, :, 2] = z_body.T

    return {
        "timestamps_s": timestamps_s,
        "satellite_positions_m": sat_local,
        "satellite_velocity_mps": vel_local,
        "satellite_positions_eci_m": r_eci,
        "body_to_local_dcm": body_to_local,
    }


def run_leo_orbit_rotation_task(
    params_config: Mapping[str, Any] | None,
    fallback_step_s: float,
    minimum_frames: int,
) -> dict[str, Any]:
    cfg, _ = build_leo_orbit_config(params_config=params_config, fallback_step_s=fallback_step_s)

    # Create enough timeline around the local zenith crossing so visibility extraction can run next.
    span_seconds = compute_horizon_visibility_span_seconds(
        earth_radius_m=cfg.earth_radius_m,
        orbital_radius_m=cfg.semi_major_axis_m,
        mean_motion_rad_s=cfg.mean_motion_rad_s,
    )
    adaptive_frames = int(span_seconds / cfg.time_step_s) + 1
    one_orbit_frames = int(math.ceil(cfg.orbital_period_s / max(cfg.time_step_s, 1e-12))) + 1
    frame_count = int(max(minimum_frames, adaptive_frames, one_orbit_frames))

    state = propagate_kepler_orbit_with_rotation(orbit_cfg=cfg, frame_count=frame_count)
    center_lat_deg = safe_float((params_config or {}).get("latitude_center"), 35.6761919)
    center_lon_deg = safe_float((params_config or {}).get("longitude_center"), 139.6503106)

    timestamps_s = np.asarray(state["timestamps_s"], dtype=float)
    r_eci = np.asarray(state["satellite_positions_eci_m"], dtype=float)
    theta = EARTH_ROTATION_RAD_S * timestamps_s
    cos_t = np.cos(theta)
    sin_t = np.sin(theta)

    x_eci = r_eci[0, :]
    y_eci = r_eci[1, :]
    z_eci = r_eci[2, :]
    x_ecef = cos_t * x_eci + sin_t * y_eci
    y_ecef = -sin_t * x_eci + cos_t * y_eci
    z_ecef = z_eci

    lat_deg = np.degrees(np.arctan2(z_ecef, np.sqrt(x_ecef * x_ecef + y_ecef * y_ecef)))
    lon_deg = np.degrees(np.arctan2(y_ecef, x_ecef))

    center_idx = int(np.argmin(np.abs(timestamps_s)))
    lat_offset = center_lat_deg - float(lat_deg[center_idx])
    lon_offset = center_lon_deg - float(lon_deg[center_idx])
    lat_deg_aligned = np.clip(lat_deg + lat_offset, -90.0, 90.0)
    lon_deg_aligned = wrap_longitude_deg(lon_deg + lon_offset)

    state["satellite_ground_track_lat_deg"] = lat_deg_aligned
    state["satellite_ground_track_lon_deg"] = lon_deg_aligned
    return state
