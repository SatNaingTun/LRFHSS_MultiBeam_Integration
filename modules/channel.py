import math

import numpy as np
import random

try:
    import astropy.units as u
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    u = None

try:
    import itur
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    itur = None

from LRFHSS.base.LRFHSSTransmission import LRFHSSTransmission
import ProjectConfig


# -----------------------------------------------------------------------------
# Constants / config helpers
# -----------------------------------------------------------------------------
EARTH_R = ProjectConfig.EARTRH_R
SAT_H = ProjectConfig.SAT_H
EARTH_G = ProjectConfig.EARTRH_G
SPEED_OF_LIGHT = ProjectConfig.SPEED_OF_LIGHT
T_FRAME = ProjectConfig.T_FRAME

# Prefer LR-FHSS carrier if available, otherwise fall back to center frequency.
DEFAULT_FREQUENCY_HZ = getattr(
    ProjectConfig,
    "OCW_FC",
    getattr(ProjectConfig, "CENTER_FREQUENCY_HZ", 868100000.0),
)

# Optional atmospheric parameters
DEFAULT_P = getattr(ProjectConfig, "p", 0.5)
DEFAULT_D = getattr(ProjectConfig, "D", 1.0)

# Channel / radio defaults
DEFAULT_RICIAN_K = getattr(ProjectConfig, "rician_k", 10.0)
DEFAULT_TX_PWR_DBM = getattr(ProjectConfig, "TX_PWR_DB", 14.0)
DEFAULT_TX_GAIN_DB = getattr(ProjectConfig, "GAIN_TX", 0.0)
DEFAULT_RX_GAIN_DB = getattr(ProjectConfig, "GAIN_RX", 0.0)


# -----------------------------------------------------------------------------
# Basic helpers
# -----------------------------------------------------------------------------
def to_dB(x):
    x = np.asarray(x, dtype=float)
    return 10.0 * np.log10(np.maximum(x, 1e-30))


def from_dB(x_db):
    return 10.0 ** (np.asarray(x_db, dtype=float) / 10.0)


def dbm_to_watt(p_dbm):
    return 10.0 ** ((p_dbm - 30.0) / 10.0)


def watt_to_dbm(p_w):
    return 10.0 * np.log10(np.maximum(np.asarray(p_w, dtype=float), 1e-30)) + 30.0


def _as_user_matrix(user_pos):
    """
    Ensure user positions are shape (3, n_user).
    """
    user_pos = np.asarray(user_pos, dtype=float)
    if user_pos.ndim != 2:
        raise ValueError("user_pos must be a 2D array with shape (3, n_user) or (n_user, 3).")

    if user_pos.shape[0] == 3:
        return user_pos
    if user_pos.shape[1] == 3:
        return user_pos.T

    raise ValueError("user_pos must have one dimension equal to 3.")


def _earth_mu(earth_r=EARTH_R, earth_g=EARTH_G):
    """
    Approximate Earth's standard gravitational parameter from surface gravity:
        mu ≈ g * R^2
    """
    return earth_g * earth_r**2


# -----------------------------------------------------------------------------
# Geometry
# -----------------------------------------------------------------------------
def center_alpha_from_elevation(elev_deg, earth_r=EARTH_R, sat_h=SAT_H):
    """
    Earth central angle alpha [rad] between:
    - serving-area center on the ground
    - subsatellite point

    This matches the spherical-Earth / circular-orbit geometry used in the
    elevation-angle LEO paper. :contentReference[oaicite:3]{index=3}
    """
    eps = np.deg2rad(elev_deg)
    orbit_r = earth_r + sat_h
    alpha = np.arccos((earth_r / orbit_r) * np.cos(eps)) - eps
    return alpha


def satellite_pos_from_center_elevation(elev_deg, earth_r=EARTH_R, sat_h=SAT_H):
    """
    Satellite position in the local coordinate system:
    - serving-area center at (0, 0, 0)
    - Earth center at (0, 0, -earth_r)
    - satellite lies in x-z plane
    """
    alpha = center_alpha_from_elevation(elev_deg, earth_r, sat_h)
    orbit_r = earth_r + sat_h

    x_sat = orbit_r * np.sin(alpha)
    y_sat = 0.0
    z_sat = orbit_r * np.cos(alpha) - earth_r

    return np.array([x_sat, y_sat, z_sat], dtype=float)


def calculate_user_satellite_distance(user_pos, satellite_pos):
    """
    Distance between each user and the satellite.

    Parameters
    ----------
    user_pos : array_like
        Shape (3, n_user) or (n_user, 3)
    satellite_pos : array_like
        Shape (3,)

    Returns
    -------
    distance_m : ndarray
        Shape (n_user,)
    """
    user_pos = _as_user_matrix(user_pos)
    satellite_pos = np.asarray(satellite_pos, dtype=float).reshape(3, 1)
    return np.linalg.norm(user_pos - satellite_pos, axis=0)


def get_user_elevation_angle(satellite_pos, user_pos, earth_r=EARTH_R):
    """
    User-specific elevation angle in degrees.

    Geometry:
    - local zenith at user position points away from Earth center
    - elevation is angle above local horizon

    Returns
    -------
    elevation_deg : ndarray
        Shape (n_user,)
    """
    user_pos = _as_user_matrix(user_pos)
    satellite_pos = np.asarray(satellite_pos, dtype=float).reshape(3, 1)

    # Earth center in this local coordinate system
    earth_center = np.array([[0.0], [0.0], [-earth_r]], dtype=float)

    # line-of-sight from user to satellite
    los_vec = satellite_pos - user_pos
    los_norm = np.linalg.norm(los_vec, axis=0)

    # local zenith direction
    zenith_vec = user_pos - earth_center
    zenith_norm = np.linalg.norm(zenith_vec, axis=0)

    cos_zenith = np.sum(los_vec * zenith_vec, axis=0) / np.maximum(los_norm * zenith_norm, 1e-30)
    cos_zenith = np.clip(cos_zenith, -1.0, 1.0)

    zenith_angle = np.arccos(cos_zenith)
    elevation_rad = (np.pi / 2.0) - zenith_angle
    return np.rad2deg(elevation_rad)


def get_positions_in_lat_long_coordinates(user_pos, earth_r=EARTH_R):
    """
    Convert Cartesian user positions to latitude / longitude in degrees.

    Coordinate system:
    - Earth center at (0, 0, -earth_r)
    - user positions are on/near Earth surface around serving-area center

    Returns
    -------
    lat_deg, lon_deg : ndarray, ndarray
        Shape (n_user,), (n_user,)
    """
    user_pos = _as_user_matrix(user_pos)
    earth_center = np.array([[0.0], [0.0], [-earth_r]], dtype=float)

    rel = user_pos - earth_center
    x = rel[0, :]
    y = rel[1, :]
    z = rel[2, :]

    r = np.linalg.norm(rel, axis=0)
    lat = np.arcsin(np.clip(z / np.maximum(r, 1e-30), -1.0, 1.0))
    lon = np.arctan2(y, x)

    return np.rad2deg(lat), np.rad2deg(lon)


# -----------------------------------------------------------------------------
# Visibility and coverage helpers
# -----------------------------------------------------------------------------
def visibility_time_from_center_elevation(
    elev_deg,
    earth_r=EARTH_R,
    sat_h=SAT_H,
):
    """
    Visibility time derived consistently from center elevation angle.

    Returns
    -------
    result : dict
        alpha_rad, alpha_deg, orbital_speed_mps, angular_speed_radps,
        half_visibility_s, full_visibility_s
    """
    alpha = center_alpha_from_elevation(elev_deg, earth_r, sat_h)
    orbit_r = earth_r + sat_h
    earth_mu = _earth_mu(earth_r, EARTH_G)

    orbital_speed = np.sqrt(earth_mu / orbit_r)
    angular_speed = np.sqrt(earth_mu / orbit_r**3)

    half_visibility_s = alpha / angular_speed
    full_visibility_s = 2.0 * half_visibility_s

    return {
        "alpha_rad": float(alpha),
        "alpha_deg": float(np.rad2deg(alpha)),
        "orbital_speed_mps": float(orbital_speed),
        "angular_speed_radps": float(angular_speed),
        "half_visibility_s": float(half_visibility_s),
        "full_visibility_s": float(full_visibility_s),
    }


def visibility_time_from_distance(d, earth_r=EARTH_R, sat_h=SAT_H):
    """
    Visibility time from slant range d [m].
    """
    d = np.asarray(d, dtype=float)
    orbit_r = earth_r + sat_h
    earth_mu = _earth_mu(earth_r, EARTH_G)

    alpha = np.arccos(
        np.clip((earth_r**2 + orbit_r**2 - d**2) / (2.0 * earth_r * orbit_r), -1.0, 1.0)
    )

    orbital_speed = np.sqrt(earth_mu / orbit_r)
    angular_speed = np.sqrt(earth_mu / orbit_r**3)

    half_visibility_s = alpha / angular_speed
    full_visibility_s = 2.0 * half_visibility_s

    return {
        "alpha_rad": alpha,
        "alpha_deg": np.rad2deg(alpha),
        "orbital_speed_mps": orbital_speed,
        "angular_speed_radps": angular_speed,
        "half_visibility_s": half_visibility_s,
        "full_visibility_s": full_visibility_s,
    }


# -----------------------------------------------------------------------------
# Legacy LR-FHSS helpers kept for compatibility
# -----------------------------------------------------------------------------
def distance_from_center_elevation(elev_deg, earth_r=EARTH_R, sat_h=SAT_H):
    """
    Legacy helper returning slant range from the serving-area center to the
    satellite for a given center elevation angle [deg].
    """
    satellite_pos = satellite_pos_from_center_elevation(elev_deg, earth_r, sat_h)
    center_pos = np.array([[0.0], [0.0], [0.0]], dtype=float)
    return float(calculate_user_satellite_distance(center_pos, satellite_pos)[0])


def get_coverageTime(r):
    """
    Legacy helper that returns coverage time from a coverage radius [m].
    """
    r = np.asarray(r, dtype=float)
    orbit_r = EARTH_R + SAT_H
    satellite_speed = get_satellite_velocity_mps()
    theta = np.arccos(
        np.clip((EARTH_R**2 + orbit_r**2 - r**2) / (2.0 * EARTH_R * orbit_r), -1.0, 1.0)
    )
    return theta * orbit_r / satellite_speed


def get_visibility_time(d):
    """
    Legacy helper that returns half visibility time from slant range [m].
    """
    return visibility_time_from_distance(d)["half_visibility_s"]


def get_FS_pathloss(d, f):
    """
    Legacy helper returning free-space channel gain in linear scale.
    """
    d = np.asarray(d, dtype=float)
    f = np.asarray(f, dtype=float)
    return (SPEED_OF_LIGHT / (4.0 * np.pi * d * f)) ** 2


def get_distance(sensitivity_dBm):
    """
    Legacy helper returning the maximum distance for a sensitivity threshold.
    """
    sensitivity_w = dbm_to_watt(sensitivity_dBm)
    tx_power_w = dbm_to_watt(DEFAULT_TX_PWR_DBM)
    tx_gain_linear = from_dB(DEFAULT_TX_GAIN_DB)
    rx_gain_linear = from_dB(DEFAULT_RX_GAIN_DB)

    a = np.sqrt(sensitivity_w / (tx_power_w * tx_gain_linear * rx_gain_linear))
    return SPEED_OF_LIGHT / (4.0 * np.pi * a * DEFAULT_FREQUENCY_HZ)


def get_coverageRadius(maxRange):
    """
    Legacy helper returning coverage radius on Earth surface [m].
    """
    maxRange = np.asarray(maxRange, dtype=float)
    x = 2.0 * EARTH_R * EARTH_R + 2.0 * SAT_H * EARTH_R
    z = (x + SAT_H**2 - maxRange**2) / x
    beta = np.arccos(np.clip(z, -1.0, 1.0))
    return beta * EARTH_R


def dopplerShift(t):
    """
    Legacy time-based Doppler model used by the original LR-FHSS code.
    """
    t = np.asarray(t, dtype=float)
    x = 1.0 + SAT_H / EARTH_R
    a = DEFAULT_FREQUENCY_HZ / SPEED_OF_LIGHT
    b = np.sqrt(EARTH_G * EARTH_R / x)
    psi = t * np.sqrt(EARTH_G / EARTH_R) / np.sqrt(x**3)
    c_term = np.sin(psi) / np.sqrt(x**2 - 2.0 * x * np.cos(psi) + 1.0)
    return a * b * c_term


def get_randomDoppler() -> float:
    """
    Legacy helper returning one random Doppler sample.
    """
    sensitivity = -137
    maxRange = get_distance(sensitivity)
    Rcov = get_coverageRadius(maxRange)
    Tcov = get_coverageTime(Rcov)

    r0 = np.sqrt(random.uniform(0.0, 1.0))
    theta0 = 2.0 * np.pi * random.uniform(0.0, 1.0)
    t0 = r0 * np.cos(theta0) * Tcov

    return float(dopplerShift(t0))


# -----------------------------------------------------------------------------
# Path loss
# -----------------------------------------------------------------------------
def get_free_space_path_loss_db(distance_m, frequency_hz=DEFAULT_FREQUENCY_HZ):
    """
    Free-space path loss in dB.

    FSPL = (4*pi*d*f/c)^2
    """
    distance_m = np.asarray(distance_m, dtype=float)
    linear = (4.0 * np.pi * distance_m * frequency_hz / SPEED_OF_LIGHT) ** 2
    return to_dB(linear)




def get_atmospheric_loss_db(
    user_pos,
    satellite_pos,
    frequency_hz=DEFAULT_FREQUENCY_HZ,
    p=DEFAULT_P,
    D=DEFAULT_D,
):
    """
    Atmospheric attenuation in dB using ITU-Rpy.

    For LR-FHSS around 868 MHz this is usually small compared with Ka-band,
    but it is kept as an optional common model component.
    """
    if itur is None or u is None:
        raise ModuleNotFoundError(
            "Atmospheric loss calculation requires optional dependencies 'itur' and 'astropy'."
        )

    user_pos = _as_user_matrix(user_pos)

    f_ghz = frequency_hz * 1e-9 * u.GHz
    elevation_angle_deg = get_user_elevation_angle(satellite_pos, user_pos)
    lat_deg, lon_deg = get_positions_in_lat_long_coordinates(user_pos)

    l_atm = itur.atmospheric_attenuation_slant_path(
        lat_deg,
        lon_deg,
        f_ghz,
        elevation_angle_deg,
        p,
        D * u.m if np.isscalar(D) else D,
    )

    return np.asarray(l_atm, dtype=float)


def path_loss(
    user_pos,
    satellite_pos,
    frequency_hz=DEFAULT_FREQUENCY_HZ,
    include_atmospheric_loss=True,
    p=DEFAULT_P,
    D=DEFAULT_D,
    elevation_deg=None,
):
    """
    Total path loss in dB = FSPL + optional atmospheric attenuation.
    """
    distance_m = calculate_user_satellite_distance(user_pos, satellite_pos)
    l_fspl_db = get_free_space_path_loss_db(distance_m, frequency_hz)

    if include_atmospheric_loss:
        l_atm_db = get_atmospheric_loss_db(
            user_pos,
            satellite_pos,
            frequency_hz=frequency_hz,
            p=p,
            D=D,
        )
    else:
        l_atm_db = np.zeros_like(l_fspl_db)
    
    if elevation_deg is not None:
        theta = np.deg2rad(elevation_deg)
        l_atm_db = l_atm_db / np.sin(theta)

    return l_fspl_db + l_atm_db

# -----------------------------------------------------------------------------
# Fading / Doppler / phase
# -----------------------------------------------------------------------------
def get_rician_fading_coefficient(n_user, rician_k=DEFAULT_RICIAN_K):
    """
    Rician fading coefficient for each user.

    Returns
    -------
    g : ndarray
        Shape (n_user, 1), complex
    """
    mu = np.sqrt(rician_k / (2.0 * (rician_k + 1.0)))
    sigma = np.sqrt(1.0 / (2.0 * (rician_k + 1.0)))

    g = (
        np.random.normal(mu, sigma, size=(n_user, 1))
        + 1j * np.random.normal(mu, sigma, size=(n_user, 1))
    )
    return g


def get_satellite_velocity_mps(earth_r=EARTH_R, sat_h=SAT_H):
    """
    Circular-orbit satellite speed.
    """
    orbit_r = earth_r + sat_h
    earth_mu = _earth_mu(earth_r, EARTH_G)
    return np.sqrt(earth_mu / orbit_r)


def get_relative_radial_velocity(satellite_pos, user_pos, earth_r=EARTH_R, sat_h=SAT_H):
    """
    Approximate per-user radial velocity for Doppler.

    Assumptions:
    - circular orbit
    - orbital motion in local x-direction / tangential direction around Earth
    - local coordinate system from the elevation model

    Returns
    -------
    radial_velocity_mps : ndarray
        Shape (n_user,)
    """
    user_pos = _as_user_matrix(user_pos)
    satellite_pos = np.asarray(satellite_pos, dtype=float).reshape(3)

    earth_center = np.array([0.0, 0.0, -earth_r], dtype=float)
    sat_rel = satellite_pos - earth_center
    sat_rel_norm = np.linalg.norm(sat_rel)

    # Tangential direction in orbital plane (x-z local orbit plane)
    # Rotate radial vector by +90 deg in x-z plane: [x,0,z] -> [z,0,-x]
    tangent = np.array([sat_rel[2], 0.0, -sat_rel[0]], dtype=float)
    tangent_norm = np.linalg.norm(tangent)
    if tangent_norm < 1e-30:
        tangent = np.array([1.0, 0.0, 0.0], dtype=float)
        tangent_norm = 1.0
    tangent = tangent / tangent_norm

    v_sat = get_satellite_velocity_mps(earth_r, sat_h)
    v_vec = v_sat * tangent

    sat_col = satellite_pos.reshape(3, 1)
    los_vec = sat_col - user_pos
    los_norm = np.linalg.norm(los_vec, axis=0)
    los_unit = los_vec / np.maximum(los_norm, 1e-30)

    radial_velocity = np.sum(v_vec.reshape(3, 1) * los_unit, axis=0)
    return radial_velocity


def get_doppler_shift(user_pos, satellite_pos, frequency_hz=DEFAULT_FREQUENCY_HZ):
    """
    Per-user Doppler shift in Hz.
    """
    radial_velocity_mps = get_relative_radial_velocity(satellite_pos, user_pos)
    return (radial_velocity_mps / SPEED_OF_LIGHT) * frequency_hz


def get_satellite_delay_phase_shift(user_pos, satellite_pos, frequency_hz=DEFAULT_FREQUENCY_HZ):
    """
    Phase shift due to propagation delay.

    Returns
    -------
    phase_shift : ndarray
        Shape (n_user, 1), complex
    """
    distance_m = calculate_user_satellite_distance(user_pos, satellite_pos)
    delay_s = distance_m / SPEED_OF_LIGHT
    phase_shift = np.exp(-2j * np.pi * delay_s[:, np.newaxis] * frequency_hz)
    return phase_shift


def get_doppler_phase_shift(user_pos, satellite_pos, i_frame, t_frame=T_FRAME, frequency_hz=DEFAULT_FREQUENCY_HZ):
    """
    Per-user phase shift due to Doppler over frame index.
    """
    doppler_hz = get_doppler_shift(user_pos, satellite_pos, frequency_hz)
    phase_shift = np.exp(-2j * np.pi * doppler_hz[:, np.newaxis] * i_frame * t_frame)
    return phase_shift


# -----------------------------------------------------------------------------
# Main LR-FHSS common effective channel
# -----------------------------------------------------------------------------
def get_effective_channel(
    user_pos,
    satellite_pos,
    i_frame=0,
    frequency_hz=DEFAULT_FREQUENCY_HZ,
    include_atmospheric_loss=True,
    include_fading=True,
    include_doppler=True,
    include_delay_phase=True,
    tx_power_dbm=DEFAULT_TX_PWR_DBM,
    tx_gain_db=DEFAULT_TX_GAIN_DB,
    rx_gain_db=DEFAULT_RX_GAIN_DB,
    rician_k=DEFAULT_RICIAN_K,
    p=DEFAULT_P,
    D=DEFAULT_D,
):
    """
    Common LR-FHSS channel model without beamforming.

    Parameters
    ----------
    user_pos : ndarray
        Shape (3, n_user) or (n_user, 3)
    satellite_pos : ndarray
        Shape (3,)
    i_frame : int
        Frame index for time evolution of Doppler phase
    frequency_hz : float
        Carrier frequency. Defaults to ProjectConfig.OCW_FC for LR-FHSS.
    include_atmospheric_loss : bool
        Include ITU atmospheric attenuation
    include_fading : bool
        Include Rician fading
    include_doppler : bool
        Include Doppler phase rotation
    include_delay_phase : bool
        Include propagation-delay phase rotation

    Returns
    -------
    result : dict
        {
            "effective_channel": (n_user, 1) complex,
            "macro_channel": (n_user, 1) complex,
            "path_loss_db": (n_user,),
            "distance_m": (n_user,),
            "elevation_deg": (n_user,),
            "doppler_hz": (n_user,),
        }
    """
    user_pos = _as_user_matrix(user_pos)
    n_user = user_pos.shape[1]

    distance_m = calculate_user_satellite_distance(user_pos, satellite_pos)
    elevation_deg = get_user_elevation_angle(satellite_pos, user_pos)

    loss_db = path_loss(
        user_pos,
        satellite_pos,
        frequency_hz=frequency_hz,
        include_atmospheric_loss=include_atmospheric_loss,
        p=p,
        D=D,
    )

    # Link budget amplitude term
    tx_power_w = dbm_to_watt(tx_power_dbm)
    gain_linear = from_dB(tx_gain_db + rx_gain_db - loss_db)
    macro_amp = np.sqrt(tx_power_w * gain_linear)[:, np.newaxis]

    # Flat LR-FHSS channel: one coefficient per user
    macro_channel = macro_amp.astype(complex)

    # Fading
    if include_fading:
        fading = get_rician_fading_coefficient(n_user, rician_k=rician_k)
    else:
        fading = np.ones((n_user, 1), dtype=complex)

    # Phase terms
    phase = np.ones((n_user, 1), dtype=complex)

    if include_doppler:
        phase *= get_doppler_phase_shift(
            user_pos,
            satellite_pos,
            i_frame=i_frame,
            t_frame=T_FRAME,
            frequency_hz=frequency_hz,
        )

    if include_delay_phase:
        phase *= get_satellite_delay_phase_shift(
            user_pos,
            satellite_pos,
            frequency_hz=frequency_hz,
        )

    effective_channel = macro_channel * fading * phase
    doppler_hz = get_doppler_shift(user_pos, satellite_pos, frequency_hz=frequency_hz)

    return {
        "effective_channel": effective_channel,
        "macro_channel": macro_channel,
        "path_loss_db": loss_db,
        "distance_m": distance_m,
        "elevation_deg": elevation_deg,
        "doppler_hz": doppler_hz,
    }


# -----------------------------------------------------------------------------
# Optional plotting helper kept from the old idea, but generic
# -----------------------------------------------------------------------------
def atmospheric_gases_plot(
    frequency_hz=DEFAULT_FREQUENCY_HZ,
    lat_deg=None,
    lon_deg=None,
    p=DEFAULT_P,
    D=DEFAULT_D,
):
    """
    Plot atmospheric attenuation over elevation angle.

    This is mostly useful for higher-frequency studies; for LR-FHSS at 868 MHz
    the attenuation is typically much smaller than in Ka-band.
    """
    if itur is None or u is None:
        raise ModuleNotFoundError(
            "Atmospheric attenuation plotting requires optional dependencies 'itur' and 'astropy'."
        )

    if lat_deg is None:
        lat_deg = getattr(ProjectConfig, "LATITUDE_CENTER_DEG", 35.6761919)
    if lon_deg is None:
        lon_deg = getattr(ProjectConfig, "LONGITUDE_CENTER_DEG", 139.6503106)

    f_ghz = frequency_hz * 1e-9 * u.GHz
    el = np.linspace(10, 90, 50)

    import matplotlib.pyplot as plt

    Ag, Ac, Ar, As, Att = itur.atmospheric_attenuation_slant_path(
        lat_deg,
        lon_deg,
        f_ghz,
        el,
        p,
        D * u.m if np.isscalar(D) else D,
        return_contributions=True,
    )

    plt.figure()
    plt.plot(el, Att.value, c="black")
    plt.plot(el, Ag.value, c="sandybrown", ls="dashed")
    plt.plot(el, Ac.value, c="powderblue", ls=(0, (5, 1)))
    plt.plot(el, Ar.value, c="steelblue", ls="dashdot")
    plt.plot(el, As.value, c="pink", ls=(0, (2, 1)))
    plt.xlabel("elevation angle (degree)")
    plt.ylabel("attenuation (dB)")
    plt.legend(
        [
            "total attenuation",
            "gaseous attenuation",
            "cloud attenuation",
            "rain attenuation",
            "scintillation attenuation",
        ]
    )
    plt.grid(which="major", linestyle=":")

def fspl_db(self, distance_m: float, frequency_hz: float) -> float:
    c = ProjectConfig.SPEED_OF_LIGHT
    return 20.0 * math.log10(4.0 * math.pi * distance_m * frequency_hz / c)


def atmospheric_loss_db_from_elevation(self, elevation_deg: float) -> float:
    """
    Simple elevation-aware atmospheric attenuation.
    For LR-FHSS this is usually small, but it creates the correct
    trend: lower elevation -> higher loss.
    """
    theta_deg = max(float(elevation_deg), 1.0)
    theta_rad = math.radians(theta_deg)

    # Tunable zenith atmospheric loss in dB.
    # Keep small for sub-GHz LR-FHSS unless you intentionally want
    # a stronger elevation penalty.
    l_zenith_db = getattr(ProjectConfig, "ATM_LOSS_ZENITH_DB", 0.5)

    return l_zenith_db / max(math.sin(theta_rad), 1e-3)


def shadowing_loss_db_from_elevation(self, elevation_deg: float) -> float:
    """
    Optional extra low-elevation penalty.
    Set coefficients to 0 if you do not want this effect.
    """
    a = getattr(ProjectConfig, "ELEV_SHADOW_A_DB", 0.0)
    b = getattr(ProjectConfig, "ELEV_SHADOW_B", 0.05)

    return a * math.exp(-b * float(elevation_deg))


def total_path_loss_db(self, distance_m: float, elevation_deg: float) -> float:
    frequency_hz = getattr(
        ProjectConfig,
        "OCW_FC",
        getattr(ProjectConfig, "CENTER_FREQUENCY_HZ", 868100000.0),
    )

    l_fspl = self.fspl_db(distance_m, frequency_hz)
    l_atm = self.atmospheric_loss_db_from_elevation(elevation_deg)
    l_shadow = self.shadowing_loss_db_from_elevation(elevation_deg)

    return l_fspl + l_atm + l_shadow


def received_signal_power_mw(self, tx: LRFHSSTransmission) -> float:
    """
    Compute elevation-aware received signal power.
    Expected tx fields:
      - tx.txPowerDbm or fallback ProjectConfig.TX_PWR_DB
      - tx.distance or tx.distance_m
      - tx.elevation or tx.elevation_deg
    """
    tx_power_dbm = getattr(tx, "txPowerDbm", getattr(ProjectConfig, "TX_PWR_DB", 14.0))

    distance_m = getattr(tx, "distance_m", getattr(tx, "distance", None))
    elevation_deg = getattr(tx, "elevation_deg", getattr(tx, "elevation", None))

    if distance_m is None:
        raise AttributeError("Transmission object must provide distance_m or distance.")
    if elevation_deg is None:
        raise AttributeError("Transmission object must provide elevation_deg or elevation.")

    total_loss_db = self.total_path_loss_db(distance_m, elevation_deg)
    rx_power_dbm = tx_power_dbm - total_loss_db
    return self.dbm_to_mw(rx_power_dbm)
