import math
import numpy as np


def safe_float(value, default: float) -> float:
    """Safely convert a value to float with fallback to default."""
    try:
        out = float(value)
        if math.isfinite(out):
            return out
    except (TypeError, ValueError):
        pass
    return float(default)


def normalize_columns(matrix: np.ndarray) -> np.ndarray:
    """Normalize matrix columns to unit length."""
    norms = np.linalg.norm(matrix, axis=0)
    norms = np.where(norms <= 1e-12, 1.0, norms)
    return matrix / norms


def rotation_matrix_r1(angle_rad: float) -> np.ndarray:
    """Rotation matrix around X-axis."""
    c = math.cos(angle_rad)
    s = math.sin(angle_rad)
    return np.array([[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]], dtype=float)


def rotation_matrix_r3(angle_rad: float) -> np.ndarray:
    """Rotation matrix around Z-axis."""
    c = math.cos(angle_rad)
    s = math.sin(angle_rad)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]], dtype=float)


def wrap_longitude_deg(lon_deg: np.ndarray) -> np.ndarray:
    """Wrap longitude to [-180, 180] degrees."""
    return ((lon_deg + 180.0) % 360.0) - 180.0


def extract_windows(mask: np.ndarray) -> list[tuple[int, int]]:
    """Extract contiguous windows from a boolean mask array."""
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


def compute_horizon_central_angle_rad(earth_radius_m: float, orbital_radius_m: float) -> float:
    """
    Compute the geometric horizon central angle (radians) for a satellite orbit.

    Returns a single scalar:
    psi = arccos(earth_radius / orbital_radius)
    """
    r_earth = float(earth_radius_m)
    r_orbit = float(orbital_radius_m)
    if r_earth <= 0.0 or r_orbit <= 0.0:
        raise ValueError("earth_radius_m and orbital_radius_m must be positive.")
    ratio = max(-1.0, min(1.0, r_earth / r_orbit))
    return float(math.acos(ratio))


def compute_semi_major_axis_m(earth_radius_m: float, altitude_m: float) -> float:
    return float(float(earth_radius_m) + float(altitude_m))


def compute_mean_motion_rad_s(earth_mu_m3_s2: float, semi_major_axis_m: float) -> float:
    mu = float(earth_mu_m3_s2)
    a = float(semi_major_axis_m)
    return float(math.sqrt(mu / max(a**3, 1e-15)))


def compute_orbital_period_s(mean_motion_rad_s: float) -> float:
    n = float(mean_motion_rad_s)
    return float((2.0 * math.pi) / max(n, 1e-12))


def compute_horizon_visibility_span_seconds(
    earth_radius_m: float,
    orbital_radius_m: float,
    mean_motion_rad_s: float,
) -> float:
    psi_horizon = compute_horizon_central_angle_rad(
        earth_radius_m=earth_radius_m,
        orbital_radius_m=orbital_radius_m,
    )
    return float((4.0 * psi_horizon) / max(float(mean_motion_rad_s), 1e-12))


def solve_kepler_equation(
    mean_anomaly_rad: np.ndarray,
    eccentricity: float,
    tol: float = 1e-12,
    max_iter: int = 30,
) -> np.ndarray:
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


def compute_free_space_path_loss_db(center_frequency_hz: float, slant_range_km: float) -> float:
    f_ghz = float(center_frequency_hz) / 1e9
    d_km = float(slant_range_km)
    return float(92.45 + 20.0 * math.log10(max(f_ghz, 1e-9)) + 20.0 * math.log10(max(d_km, 1e-9)))


def compute_noise_floor_dbm(noise_bandwidth_hz: float, noise_figure_db: float) -> float:
    return float(-174.0 + 10.0 * math.log10(max(float(noise_bandwidth_hz), 1e-9)) + float(noise_figure_db))


def compute_doppler_shift_hz(radial_speed_mps: float, center_frequency_hz: float, speed_of_light_mps: float) -> float:
    return float((float(radial_speed_mps) / max(float(speed_of_light_mps), 1e-12)) * float(center_frequency_hz))


def compute_mean_altitude_km(radii_m: np.ndarray, earth_radius_m: float) -> float:
    altitudes_km = (np.asarray(radii_m, dtype=float) - float(earth_radius_m)) / 1000.0
    return float(np.mean(altitudes_km))


def compute_mean_speed_km_s(positions_m: np.ndarray, step_seconds: float) -> float:
    pos = np.asarray(positions_m, dtype=float)
    dt = float(step_seconds)
    vel = np.diff(pos, axis=1) / max(dt, 1e-12)
    if vel.shape[1] <= 0:
        return 0.0
    return float(np.mean(np.linalg.norm(vel, axis=0)) / 1000.0)


def compute_inclination_deg_from_positions(sat_pos: np.ndarray) -> float:
    pos = np.asarray(sat_pos, dtype=float)
    if pos.shape[1] < 2:
        return 0.0
    h_vec = np.cross(pos[:, 0], pos[:, 1])
    h_norm = float(np.linalg.norm(h_vec))
    if h_norm <= 0.0:
        return 0.0
    ratio = max(-1.0, min(1.0, float(h_vec[2]) / h_norm))
    return float(np.degrees(np.arccos(ratio)))
