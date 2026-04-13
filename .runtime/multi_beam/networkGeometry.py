import numpy as np

import params
import utils


def get_satellite_pos():
    """
    Calculate satellite positions in meter in Cartesian coordinates centered at satellite footprint center.
    Create coordinates on a circle arc at the satellite altitude and then re-center the coordinates to
    the center of the footprint of the satellite. One 3D position is created per frame.

    :return: [x_sat, y_sat, z_sat] array of size (3, n_position) satellite positions over frames in Cartesian
    coordinates centered around footprint center. n_position is the number of frames the satellite needs to travel its
    visibility region as seen from the center point of the observed footprint.
    """
    config = params.read_params()
    t_frame = config["t_frame"]
    r_earth = config["r_earth"]
    v_satellite = config["v_satellite"]
    h_satellite = config["h_satellite"]

    # create positions on arc in polar coordinates
    altitude = r_earth + h_satellite  # in meter - radius of circle on which to position satellite
    delt_eps_center = (v_satellite * t_frame) / altitude  # change of angle (from center of Earth) for traveled distance
    # minimum elevation angle for satellite to be visible from footprint center
    eps_zero = np.pi / 2 - np.arccos(r_earth / altitude)
    # array of angles from center of Earth in radians (n_position, )
    eps = np.arange(eps_zero, np.pi - eps_zero, delt_eps_center)

    # create positions in Cartesian coordinates
    [x_sat, z_sat] = utils.pol2cart(altitude, eps)
    y_sat = np.zeros_like(x_sat)
    # re-center coordinates around center of satellite footprint
    z_sat = z_sat - r_earth
    return np.array([x_sat, y_sat, z_sat])  # (3, n_position)


def get_user_position(n_user):
    """
    Randomly distribute the given number of positions on a spherical surface with footprint radius from parameter file.
    For a uniform distribution on a sphere of radius r, phi is uniformly distributed between 0 and 2pi, and for theta,
    we need to take arccos(1-2u), where u is uniformly distributed between 0 and theta_max, where
    theta_max = 0.5 - cos(theta_lim).
    :param n_user: number of positions to create
    :return: (3, n_user) Cartesian coordinates of user positions centered around footprint center
    """
    config = params.read_params()
    r_footprint = config["r_footprint"]
    r_earth = config["r_earth"]

    # make sure points are evenly distributed on sphere
    theta = np.arccos(np.random.uniform(np.cos(r_footprint / r_earth), 1, n_user))
    phi = np.random.uniform(0, 2 * np.pi, n_user)
    # convert to Cartesian coordinates
    [x_user, y_user, z_user] = utils.pol2cart3D(r_earth, phi, theta)
    z_user = z_user - r_earth  # re-center coordinates around center of satellite footprint
    return np.array([x_user, y_user, z_user])  # (3, n_user)


def get_grid_positions(user_distance):
    """
    Create grid positions in the satellite footprint region.
    :param user_distance: distance between two user positions in meter.
    :return: (3, n_user) Cartesian coordinates of grid positions
    """
    config = params.read_params()
    r_footprint = config["r_footprint"]
    r_earth = config["r_earth"]
    n_tier = int(np.ceil(r_footprint / user_distance + 1))
    x_user = np.zeros(int(np.sum(np.arange(n_tier+1)) * 6 +n_tier))
    y_user = np.zeros(int(np.sum(np.arange(n_tier+1)) * 6 +n_tier))
    z_user = r_earth * np.ones(int(np.sum(np.arange(n_tier+1)) * 6 +n_tier))

    i_start = 1  # starting index
    for i_tier in range(1, n_tier+1):
        i_stop = i_start + i_tier * 6  # stopping index
        phi = np.linspace(0, 2 * np.pi, i_tier*6)
        theta = r_footprint / n_tier / r_earth * i_tier * np.ones_like(phi)
        # convert to Cartesian coordinates
        [x_user[i_start:i_stop], y_user[i_start:i_stop], z_user[i_start:i_stop]] = utils.pol2cart3D(r_earth, phi, theta)
        i_start = i_stop + 1
    z_user = z_user - r_earth  # re-center coordinates around center of satellite footprint
    return np.array([x_user, y_user, z_user])  # (3, n_user)


def hex_grid_centers_two_rings():
    """
    Creates the centers of two rings (+ center) of a flat-topped  hexagonal grid on Earth's surface.
    :return: hex_center (3, 19) array with [x,y,z] positions of centers
    """
    config = params.read_params()
    r_footprint = config["r_footprint"]
    r_earth = config["r_earth"]

    # set azimuth angle starting in upper left corner of pointy topped hexagonal grid with two rings
    phi_hex = np.pi / 2 + np.pi / 6 * np.array([4, 3, 2,  # top row
                                                5, 4, 2, 1,  # second row
                                                6, 6, 0, 0, 0,  # center row
                                                7, 8, 10, 11,  # fourth row
                                                8, 9, 10])  # bottom row
    # set elevation angle starting in upper left corner of pointy topped hexagonal grid with two rings
    theta_side = 1 / np.cos(np.pi / 6)  # factor converting hexagon radius to hexagon side length
    # 2*r_footprint/10 is the radius of a hexagonal cell (distance from center to center of side)
    theta_hex = 2 * r_footprint / 10 / r_earth * np.array([4, 3 * theta_side, 4,
                                                           3 * theta_side, 2, 2, 3 * theta_side,
                                                           4, 2, 0, 2, 4,
                                                           3 * theta_side, 2, 2, 3 * theta_side,
                                                           4, 3 * theta_side, 4])
    [x_hex, y_hex, z_hex] = utils.pol2cart3D(r_earth, phi_hex, theta_hex)  # convert to Cartesian coordinates
    hex_center = np.array([x_hex, y_hex, z_hex - r_earth])  # re-center to footprint center and stack into (3, 19) array
    return hex_center  # (3, 19)
