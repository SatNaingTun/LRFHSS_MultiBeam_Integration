from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from typing import Any, Mapping

import numpy as np

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
        return float(self.earth_radius_m + self.altitude_m)

    @property
    def mean_motion_rad_s(self) -> float:
        return float(math.sqrt(self.earth_mu_m3_s2 / (self.semi_major_axis_m**3)))

    @property
    def orbital_period_s(self) -> float:
        return float((2.0 * math.pi) / max(self.mean_motion_rad_s, 1e-12))


def _safe_float(value: Any, default: float) -> float:
    try:
        out = float(value)
        if math.isfinite(out):
            return out
    except (TypeError, ValueError):
        pass
    return float(default)


def _normalize_columns(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=0)
    norms = np.where(norms <= 1e-12, 1.0, norms)
    return matrix / norms


def _r1(angle_rad: float) -> np.ndarray:
    c = math.cos(angle_rad)
    s = math.sin(angle_rad)
    return np.array([[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]], dtype=float)


def _r3(angle_rad: float) -> np.ndarray:
    c = math.cos(angle_rad)
    s = math.sin(angle_rad)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]], dtype=float)


def _wrap_longitude_deg(lon_deg: np.ndarray) -> np.ndarray:
    return ((lon_deg + 180.0) % 360.0) - 180.0


def solve_kepler_equation(mean_anomaly_rad: np.ndarray, eccentricity: float, tol: float = 1e-12, max_iter: int = 30) -> np.ndarray:
    e = float(max(0.0, min(0.999999, eccentricity)))
    m = np.asarray(mean_anomaly_rad, dtype=float)
    m_wrapped = np.mod(m, 2.0 * math.pi)
    ecc_anomaly = np.where(e < 0.8, m_wrapped, np.pi * np.ones_like(m_wrapped))

    for _ in range(max_iter):
        f = ecc_anomaly - e * np.sin(ecc_anomaly) - m_wrapped
        fp = 1.0 - e * np.cos(ecc_anomaly)
        delta = -f / np.where(np.abs(fp) < 1e-15, 1e-15, fp)
        ecc_anomaly = ecc_anomaly + delta
        if np.max(np.abs(delta)) < tol:
            break

    return ecc_anomaly


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

    earth_radius_m = _safe_float(params_config.get("r_earth"), defaults.earth_radius_m)
    altitude_m = _safe_float(params_config.get("h_satellite"), defaults.altitude_m)
    time_step_s = _safe_float(params_config.get("t_frame"), defaults.time_step_s)

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
    eccentricity = _safe_float(params_config.get("orbit_eccentricity"), defaults.eccentricity)
    inclination_deg = _safe_float(params_config.get("orbit_inclination_deg"), defaults.inclination_deg)
    raan_deg = _safe_float(params_config.get("orbit_raan_deg"), defaults.raan_deg)
    arg_perigee_deg = _safe_float(params_config.get("orbit_arg_perigee_deg"), defaults.arg_perigee_deg)
    mean_anomaly_epoch_deg = _safe_float(params_config.get("orbit_mean_anomaly_epoch_deg"), defaults.mean_anomaly_epoch_deg)

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
    mean_anomaly = m0 + mean_motion * timestamps_s
    ecc_anomaly = solve_kepler_equation(mean_anomaly, e)

    sin_e = np.sin(ecc_anomaly)
    cos_e = np.cos(ecc_anomaly)
    radius = a * (1.0 - e * cos_e)

    beta = math.sqrt(max(1.0 - e * e, 1e-15))
    true_anomaly = np.arctan2(beta * sin_e, cos_e - e)
    p = a * (1.0 - e * e)

    # Perifocal state vectors (Curtis/Vallado).
    r_pqw = np.vstack((radius * np.cos(true_anomaly), radius * np.sin(true_anomaly), np.zeros_like(radius)))
    vel_scale = math.sqrt(mu / max(p, 1e-15))
    v_pqw = np.vstack((
        -vel_scale * np.sin(true_anomaly),
        vel_scale * (e + np.cos(true_anomaly)),
        np.zeros_like(radius),
    ))

    q_pqw_to_eci = _r3(raan) @ _r1(inc) @ _r3(argp)
    r_eci = q_pqw_to_eci @ r_pqw
    v_eci = q_pqw_to_eci @ v_pqw

    # Build footprint-centered local frame using the epoch sub-satellite point.
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
    footprint_center_eci = orbit_cfg.earth_radius_m * z_axis

    sat_local = q_eci_to_local @ (r_eci - footprint_center_eci[:, None])
    vel_local = q_eci_to_local @ v_eci

    # Nadir-pointing body frame rotation per sample.
    sat_from_earth_center_local = sat_local.copy()
    sat_from_earth_center_local[2, :] += orbit_cfg.earth_radius_m
    radial_hat = _normalize_columns(sat_from_earth_center_local)

    tangential = vel_local - radial_hat * np.sum(vel_local * radial_hat, axis=0, keepdims=True)
    x_body = _normalize_columns(tangential)
    z_body = -radial_hat
    y_body = _normalize_columns(np.cross(z_body.T, x_body.T).T)
    x_body = _normalize_columns(np.cross(y_body.T, z_body.T).T)

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
        "orbit_frame": {
            "x_axis": x_axis,
            "y_axis": y_axis,
            "z_axis": z_axis,
        },
    }


def run_leo_orbit_rotation_task(
    params_config: Mapping[str, Any] | None,
    fallback_step_s: float,
    minimum_frames: int,
) -> dict[str, Any]:
    cfg, source_meta = build_leo_orbit_config(params_config=params_config, fallback_step_s=fallback_step_s)

    # Create enough timeline around the local zenith crossing so visibility extraction can run next.
    psi_horizon = math.acos(max(-1.0, min(1.0, cfg.earth_radius_m / cfg.semi_major_axis_m)))
    span_seconds = float((4.0 * psi_horizon) / max(cfg.mean_motion_rad_s, 1e-12))
    adaptive_frames = int(span_seconds / cfg.time_step_s) + 1
    one_orbit_frames = int(math.ceil(cfg.orbital_period_s / max(cfg.time_step_s, 1e-12))) + 1
    frame_count = int(max(minimum_frames, adaptive_frames, one_orbit_frames))

    state = propagate_kepler_orbit_with_rotation(orbit_cfg=cfg, frame_count=frame_count)
    center_lat_deg = _safe_float((params_config or {}).get("latitude_center"), 35.6761919)
    center_lon_deg = _safe_float((params_config or {}).get("longitude_center"), 139.6503106)

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
    lon_deg_aligned = _wrap_longitude_deg(lon_deg + lon_offset)

    state["satellite_ground_track_lat_deg"] = lat_deg_aligned
    state["satellite_ground_track_lon_deg"] = lon_deg_aligned
    state["orbit_task"] = {
        "task": "check_leo_orbit_or_default_then_kepler_rotation",
        "algorithm": [
            "two_body_kepler_propagation_classical_orbital_elements",
            "newton_raphson_kepler_equation_solver",
        ],
        "citations": [
            "Vallado, Fundamentals of Astrodynamics and Applications (4th ed.)",
            "Curtis, Orbital Mechanics for Engineering Students (4th ed.)",
        ],
        "config_source": source_meta,
        "orbit_config": asdict(cfg),
        "frame_count": frame_count,
        "earth_rotation_rad_s": EARTH_ROTATION_RAD_S,
        "ground_track_reference_center": {
            "latitude_deg": center_lat_deg,
            "longitude_deg": center_lon_deg,
        },
    }
    return state
