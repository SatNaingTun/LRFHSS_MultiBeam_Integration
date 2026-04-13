import json

import utils


def update_param_file(r_footprint):
    """
    Write parameter file with given footprint and parameters set in this function.
    :param r_footprint: satellite footprint radius in meter
    :return:
    """
    config = {
        "r_footprint": r_footprint,  # radius of satellite footprint in meter
        "h_satellite": 600e3,  # altitude of LEO satellite in meter (600 km)
        "center_frequency": 30e9,  # center frequency in Hz
        "bandwidth_Hz": 25e6,  # bandwidth in Hz
        "n_antenna_x": 32,  # number of antennas per beam in x direction
        "n_antenna_y": 32,  # number of antennas per beam in y direction
        "antenna_gain_dB": 60.5,  # antenna array gain
        "rician_k": 10,  # Rician K-factor
        "transmit_power_W": 63,  # transmit power
        "n_beams_x": 5,  # number of beams in x direction of antenna array
        "n_beams_y": 4,  # number of beams in y direction of antenna array
        "n_beams": 19,  # total number of beams
        "noise_figure_dB": 7,  # receiver noise figure in dB according to 3GPP TR 38.821
        "t_frame": 10e-3,  # time between two satellite positions
        "r_earth": 6371e3,  # radius of planet Earth in meter
        "v_satellite": 7.56e3,  # velocity of LEO satellite in meter per second (7.56 km/s)
        "SPEED_OF_LIGHT": 299792458,  # speed of light in vacuum in meter per second
        "BOLTZMANN_CONSTANT": 1.3806485e-23,  # Boltzmann's constant in m^2*kg*s^(-2)/K
        "temperature_K": 300,  # temperature of user equipment in Kelvin (for noise power calculation)
        "latitude_center": 35.67619190,  # latitude ground coordinates center (Tokyo)
        "longitude_center": 139.65031060,  # longitude ground coordinates center (Tokyo)
        "D": 0,  # Antenna diameters for atmospheric loss calculation
        "p": 1,  # Unavailability (Values exceeded 1% of time) for atmospheric loss calculation
    }
    with open('params.json', 'w') as f:
        json.dump(config, f)


def get_antenna_spacing():
    """
    Calculate the distance between antenna elements assuming an antenna spacing of lambda/2, i.e., return lambda/2.
    :return: antenna_spacing in meter
    """
    config = read_params()
    center_frequency = config["center_frequency"]
    SPEED_OF_LIGHT = config["SPEED_OF_LIGHT"]
    antenna_spacing = SPEED_OF_LIGHT/center_frequency/2
    return antenna_spacing


def get_noise_power():
    """
    Calculate noise power over bandwidth.
    :return: noise power in Watt
    """
    config = read_params()
    k_B = config["BOLTZMANN_CONSTANT"]
    bandwidth = config["bandwidth_Hz"]
    t_K = config["temperature_K"]
    noise_figure_dB = config["noise_figure_dB"]
    # calculate thermal noise power including noise figure, i.e.,  kTB + noise figure (in dB)
    noise_power_W = k_B * t_K * bandwidth * utils.from_dB(noise_figure_dB)
    return noise_power_W


def read_params():
    """
    Load parameter configuration from parameter json file.
    :return: config
    """
    with open('params.json', 'r') as f:
        config = json.load(f)
    return config
