import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path
import sys

try:
    from ProjectConfig import (
        ANTENNA_SPACING_M,
        EARTRH_R,
        LATITUDE_CENTER_DEG,
        LONGITUDE_CENTER_DEG,
        N_ANTENNA_X,
        N_ANTENNA_Y,
        N_BEAMS_X,
        N_BEAMS_Y,
    )
except ModuleNotFoundError:
    _PROJECT_ROOT = Path(__file__).resolve().parents[1]
    if str(_PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(_PROJECT_ROOT))
    from ProjectConfig import (
        ANTENNA_SPACING_M,
        EARTRH_R,
        LATITUDE_CENTER_DEG,
        LONGITUDE_CENTER_DEG,
        N_ANTENNA_X,
        N_ANTENNA_Y,
        N_BEAMS_X,
        N_BEAMS_Y,
    )


def to_dB(linear_value):
    """
    Convert linear values into dB.
    :param linear_value: value or numpy array of values to convert into dB
    :return: input values in dB - same dimension as input
    """
    dB_value = 10 * np.log10(linear_value)
    return dB_value


def from_dB(dB_value):
    """
    Convert values in dB into linear values.
    :param dB_value: value or numpy array of values in dB
    :return: linear values of same dimension as input
    """
    linear_value = 10 ** (dB_value / 10)
    return linear_value


def pol2cart(rho, phi):
    """
    Convert 2D polar coordinates to 2D Cartesian coordinates.
    :param rho: radius of polar coordinates
    :param phi: angle of polar coordinates in rad
    :return: [x, y] Cartesian coordinates
    """
    x = rho * np.cos(phi)
    y = rho * np.sin(phi)
    return x, y


def pol2cart3D(r, phi, theta):
    """
    Convert 3D polar coordinates to 3D Cartesian coordinates.
    :param r: radius of polar coordinates
    :param phi: azimuth angle of polar coordinates in rad
    :param theta: elevation angle of polar coordinates in rad
    :return: [x, y, z] Cartesian coordinates
    """
    x = r * np.sin(theta) * np.cos(phi)
    y = r * np.sin(theta) * np.sin(phi)
    z = r * np.cos(theta)
    return x, y, z


def cart2pol3D(x, y, z):
    """
    Convert 3D Cartesian coordinates to spherical coordinates (physics convention).
    :param x: Cartesian x coordinate
    :param y: Cartesian y coordinate
    :param z: Cartesian z coordinate
    :return: [r, phi, theta] spherical coordinates (physics convention) - phi and theta in rad
    """
    r = np.sqrt(x ** 2 + y ** 2 + z ** 2)
    phi = np.zeros_like(r)
    zer = ((x == 0) & (y == 0))
    phi[zer] = 0
    phi[~zer] = sign(y[~zer]) * np.arccos(x[~zer] / np.sqrt(x[~zer] ** 2 + y[~zer] ** 2))
    theta = np.arccos(z / r)
    return r, phi, theta


def rad2deg(angle_rad):
    """
    Convert angle in degree to angle in radian.
    :param angle_rad:
    :return: angle_deg same size as input
    """
    angle_deg = angle_rad / np.pi * 180
    return angle_deg


def deg2rad(angle_deg):
    """
    Convert angle in radian to angle in degree.
    :param angle_deg:
    :return: angle_rad same size as input
    """
    angle_rad = angle_deg / 180 * np.pi
    return angle_rad


def sign(x):
    """
    Return 1 if sign is positive or zero and -1 else.
    NOTE: this is necessary, because the np.sign() function returns 0 for an input of 0.
    :param x: array of real values
    :return: sign of input values
    """
    sign_x = np.ones_like(x)
    sign_x[x < 0] = -1
    return sign_x


def complex_zeros(size):
    """
    Return a complex array of the specified size.
    :param size: dimension of complex zeros array
    :return: complex array of zeros of specified size
    """
    c_zero = np.zeros(size) + 1j*np.zeros(size)
    return c_zero


def get_angles_to_satellite(satellite_pos, user_pos):
    """
    Transform coordinate system so that the corner of the satellite array is at the center of the coordinate system and
    oriented in direction of the positive z-axis and calculate angles between users and satellites for array steering.
    :param satellite_pos: (3,) (x,y,z) satellite position in Cartesian coordinates
    :param user_pos: (3, n_user) (x,y,z) user positions in Cartesian coordinates
    :return:
    phi (1, n_user) azimuth angle from satellite array to user position in rad
    theta (1, n_user) elevation angle from satellite array to user position in rad
    user_pos_t (3, n_user) rotated (x,y,z) user positions in Cartesian coordinates
    """
    r_earth = float(EARTRH_R)
    n_antenna_x = int(N_ANTENNA_X)
    n_antenna_y = int(N_ANTENNA_Y)
    n_beams_x = int(N_BEAMS_X)
    n_beams_y = int(N_BEAMS_Y)

    # move coordinate system by size of the antenna array to have corner of array at center
    satellite_pos[0] = satellite_pos[0] - n_antenna_x * n_beams_x / 2 * float(ANTENNA_SPACING_M)
    satellite_pos[1] = satellite_pos[1] - n_antenna_y * n_beams_y / 2 * float(ANTENNA_SPACING_M)
    # move satellite to center of coordinate system
    user_pos_t = user_pos - satellite_pos[:, np.newaxis]
    # rotate user positions to have satellite array orientation in direction of positive z-axis
    tan_vec = np.array([1, -satellite_pos[0]/(satellite_pos[2]+r_earth)])  # tangent vector to satellite trajectory
    rotation_angle = np.arccos(tan_vec[0] / np.linalg.norm(tan_vec)) * sign(satellite_pos[0]) + np.pi
    T = np.array([[np.cos(rotation_angle), 0, -np.sin(rotation_angle)],  # rotation matrix
                  [0,           1, 0],
                  [np.sin(rotation_angle), 0, np.cos(rotation_angle)]])
    user_pos_t = T @ user_pos_t  # apply rotation to user positions

    # get angles between beam center and satellite
    _, phi, theta = cart2pol3D(user_pos_t[0, :], user_pos_t[1, :], user_pos_t[2, :])
    phi = phi[np.newaxis, :]  # (1000, ) -> (1, 1000)
    theta = theta[np.newaxis, :]  # (1000, ) -> (1, 1000)

    return phi, theta, user_pos_t


def get_positions_in_lat_long_coordinates(user_pos):
    """
    Calculate latitude and longitude coordinates of user positions.
    :param user_pos: (3, n_user) Cartesian coordinates in coordinate system centered at footprint center.
    :return: lat_deg (n_user,), lon_deg (n_user,) latitude and longitude on spherical Earth in degree
    """

    r_earth = float(EARTRH_R)
    latitude_center = float(LATITUDE_CENTER_DEG)
    longitude_center = float(LONGITUDE_CENTER_DEG)

    x, y, z = pol2cart3D(r_earth, latitude_center/180*np.pi, longitude_center/180*np.pi)
    _, lat_rad, lon_rad = cart2pol3D(x + user_pos[0, :], y + user_pos[1, :], z + user_pos[2, :])
    lat_deg = rad2deg(lat_rad)
    lon_deg = rad2deg(lon_rad)

    return lat_deg, lon_deg


def get_user_elevation_angle(satellite_pos, user_pos):
    """
    Calculate elevation angle to satellite for each user position.
    :param satellite_pos: (3,)
    :param user_pos: (3, n_user)
    :return: (n_user) elevation angle in degree to satellite for each user position
    """
    sat_to_user = satellite_pos[:, np.newaxis] - user_pos
    _, _, elevation_angle = cart2pol3D(sat_to_user[0, :], sat_to_user[1, :], sat_to_user[2, :])
    return 90 - np.abs(np.mod(rad2deg(elevation_angle), 90))


def array_steering_matrix(Phi_x, Phi_y):
    """
    Calculate the array steering matrix. Matrix is not normalized and needs to be normalized outside of this function.
    :param Phi_x: (1, n_user)
    :param Phi_y: (1, n_user)
    :return: a: (n_antenna_x*n_beams_x, n_antenna_y*n_beams_y, n_user) array steering matrix
    """
    n_beams_x = int(N_BEAMS_X)
    n_beams_y = int(N_BEAMS_Y)
    n_antenna_x = int(N_ANTENNA_X)
    n_antenna_y = int(N_ANTENNA_Y)
    n_user = np.max(np.size(Phi_x))

    # get array steering vector for a user
    x_antenna = np.arange(n_antenna_x * n_beams_x)
    x_antenna = x_antenna[:, np.newaxis]
    y_antenna = np.arange(n_antenna_y * n_beams_y)
    y_antenna = y_antenna[:, np.newaxis]
    v_x = np.exp(1j * np.pi * Phi_x * x_antenna)  # [n_antenna x n_user]
    v_y = np.exp(1j * np.pi * Phi_y * y_antenna)

    a = np.empty([n_antenna_x * n_beams_x, n_antenna_y * n_beams_y, n_user], dtype=complex)
    for iUser in range(n_user):
        a[:, :, iUser] = np.kron(v_x[:, iUser, np.newaxis], v_y[:, iUser])
    return a  # (n_antenna_x*n_beams_x, n_antenna_y*n_beams_y, n_user)


def get_beam_coefficients(a, i_beam):
    """
    Read out the coefficients of an array steering matrix of the same dimension as the antenna array (number of
    antennas in x-direction times number of antennas in y-direction) into a vector for the specified beam. This function
    is necessary to support more or less arbitrary antenna array dimensions that do not necessarily fill a rectangular
    grid.
    :param a: (n_antenna_x*n_beams_x, n_antenna_y*n_beams_y) complex array steering factors
    :param i_beam: beam index for which we want to read out the array steering factors
    :return: (n_antenna_x*n_antenna_y, ) antenna array steering coefficients of designated beam beam_i
    """
    n_beams_x = int(N_BEAMS_X)
    n_beams_y = int(N_BEAMS_Y)
    n_antenna_x = int(N_ANTENNA_X)
    n_antenna_y = int(N_ANTENNA_Y)

    x_start = np.mod(i_beam, n_beams_x) * n_antenna_x
    y_start = np.mod(i_beam, n_beams_y) * n_antenna_y
    a_beam = a[x_start:(x_start + n_antenna_x), y_start:(y_start + n_antenna_y)]
    return a_beam.ravel()


def get_elevation_angle_from_center(x_sat, z_sat):
    """
    Calculate elevation angle in radian from footprint center to given satellite position. The y-coordinate of the
    satellite is assumed to be zero.
    :param x_sat: x-coordinate of satellite position
    :param z_sat: z-coordinate of satellite position
    :return: elevation angle of satellite position from footprint center in radian
    """
    elevation_angle = np.zeros_like(x_sat)
    if np.any(x_sat == 0):
        elevation_angle[np.abs(x_sat) != 0] = np.arctan(z_sat[x_sat != 0] / np.abs(x_sat[x_sat != 0]))
        elevation_angle[x_sat == 0] = np.pi/2
    else:
        elevation_angle = np.array(np.arctan(z_sat / np.abs(x_sat)))
    if np.any(x_sat < 0):
        elevation_angle[x_sat < 0] = np.pi - elevation_angle[x_sat < 0]
    return elevation_angle


def plot_ecdf(values, col, l_style='solid'):
    """
    Plot ECDF of given values.
    :param l_style: string with line style
    :param col: string with color name
    :param values: (n_values, )
    :return:
    """
    counts, bin_edges = np.histogram(values, bins=len(np.unique(values)))
    cdf = np.cumsum(counts)/len(values)
    plt.figure()
    plt.grid(True)
    plt.plot(bin_edges[1:], cdf, color=col, linestyle=l_style, linewidth=2.5)
    plt.ylabel("ECDF")
    plt.ylim([0, 1])


def plot_ecdf_same_figure(values, col, l_style='solid'):
    """
    Plot ECDF of given values in existing figure.
    :param l_style: string with line style
    :param col: string with color name
    :param values: (n_values, )
    :return:
    """
    counts, bin_edges = np.histogram(values, bins=len(np.unique(values)))
    cdf = np.cumsum(counts)/len(values)
    plt.plot(bin_edges[1:], cdf, linestyle=l_style, linewidth=2.5, color=col)


def calculate_user_satellite_distance(user_pos, satellite_pos):
    """
    Calculate the distance between the set of users given by user_pos and the given satellite position in meter.
    :param user_pos: (3, n_user) user positions in Cartesian coordinates
    :param satellite_pos: (3, ) satellite position in Cartesian coordinates
    :return: distance_m (n_user, ) distance between user and satellite in meter
    """
    # calculate distance from each user to satellite
    satellite_pos = satellite_pos[:, np.newaxis]
    distance_m = np.linalg.norm(user_pos-satellite_pos, axis=0)
    return distance_m
