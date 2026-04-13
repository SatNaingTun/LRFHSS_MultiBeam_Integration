import astropy.units as u
import itur
import matplotlib.pyplot as plt
import numpy as np

import params
import utils


def path_loss(user_pos, satellite_pos):
    """
    Return free space path loss with atmospheric attenuation loss for each user position.
    :param user_pos: (3, n_user) Cartesian user positions in meter
    :param satellite_pos: (3,) Cartesian satellite position in meter
    :return: loss_dB (n_user, ) loss due to FSPL and atmospheric attenuation in dB
    """
    config = params.read_params()
    frequency_Hz = config["center_frequency"]
    f = frequency_Hz * 1e-9 * u.GHz
    speed_of_light = config["SPEED_OF_LIGHT"]
    p = config["p"]
    D = config["D"] * u.m

    # calculate free space path loss
    distance_m = utils.calculate_user_satellite_distance(user_pos, satellite_pos)
    l_fspl = utils.to_dB((4*np.pi*distance_m*frequency_Hz/speed_of_light)**2)

    # calculate atmospheric loss
    elevation_angle_deg = utils.get_user_elevation_angle(satellite_pos, user_pos)
    lat_deg, lon_deg = utils.get_positions_in_lat_long_coordinates(user_pos)
    l_atmospheric_dB = itur.atmospheric_attenuation_slant_path(lat_deg, lon_deg, f, elevation_angle_deg, p, D)

    # combine free space and atmospheric losses
    loss_dB = l_fspl + np.array(l_atmospheric_dB)
    return loss_dB


def atmospheric_gases_plot():
    """
    Plot atmospheric losses over elevation angles according to:
    @misc{iturpy-2017,
      title={ITU-Rpy: A python implementation of the ITU-R P. Recommendations to compute
         atmospheric attenuation in slant and horizontal paths.},
      author={Inigo del Portillo},
      year={2017},
      publisher={GitHub},
      howpublished={\ url{https://github.com/inigodelportillo/ITU-Rpy/}}
    }
    :return:
    """
    config = params.read_params()
    f = config["center_frequency"] * 1e-9 * u.GHz
    p = config["p"]
    D = config["D"] * u.m
    lat_GS = config["latitude_center"]
    lon_GS = config["longitude_center"]

    # vector of elevation angles
    el = np.linspace(10, 90, 50)

    # calculate attenuation values with itur model
    Ag, Ac, Ar, As, Att = itur.atmospheric_attenuation_slant_path(lat_GS, lon_GS, f, el, p, D, return_contributions=True)
    # plot figure 5 in paper
    plt.figure()
    plt.plot(el, Att.value, c='black')
    plt.plot(el, Ag.value, c='sandybrown', ls='dashed')
    plt.plot(el, Ac.value, c='powderblue', ls=(0, (5, 1)))
    plt.plot(el, Ar.value, c='steelblue', ls='dashdot')
    plt.plot(el, As.value, c='pink', ls=(0, (2, 1)))
    plt.xlabel('elevation angle $\epsilon$ (degree)')
    plt.ylabel('attenuation (dB)')
    plt.legend(['total attenuation', 'gaseous attenuation', 'clouds attenuation', 'rain attenuation',
                'scintillation attenuation'])
    plt.grid(which='major', linestyle=':')


def get_array_steering_vector(satellite_pos, user_pos):
    """
    Calculate array steering vector for each user. The array steering vector is the phase shift induced by the path
    length differences from the different antenna positions.
    :param satellite_pos: (3, 1) Cartesian satellite position for which array steering vector is calculated
    :param user_pos: (3, n_user) Cartesian user coordinates
    :return: (n_user, n_antenna_total) complex normalized array steering coefficient matrix per antenna element
    """
    config = params.read_params()
    n_beams = config["n_beams"]
    n_antenna_x = config["n_antenna_x"]
    n_antenna_y = config["n_antenna_y"]

    # prepare angle vector for all users
    phi, theta, user_pos_t = utils.get_angles_to_satellite(satellite_pos, user_pos)
    Phi_x = np.cos(phi)*np.sin(theta)
    Phi_y = np.sin(phi)*np.sin(theta)
    # get array steering vector
    a = utils.array_steering_matrix(Phi_x, Phi_y)

    # reshape to (n_user, n_antenna_total) complex matrix and drop entries for which we don't have antennas
    n_user = np.size(user_pos_t, axis=1)
    a_final = np.empty([n_user, n_antenna_x*n_antenna_y*n_beams], dtype=complex)
    for i_beam in range(n_beams):
        beam_start = i_beam*n_antenna_x*n_antenna_y
        beam_end = beam_start + n_antenna_x*n_antenna_y
        for i_user in np.arange(n_user):
            a_final[i_user, beam_start:beam_end] = utils.get_beam_coefficients(a[:, :, i_user], i_beam)
    return a_final / np.sqrt(n_antenna_x*n_antenna_y*n_beams)


def fixed_beam_steering(satellite_pos, beam_centers):
    """
    Return analog precoder for fixed beam centers.
    The returned analog precoder is in block diagonal matrix form with one column per beam.
    :param satellite_pos: (3, 1) array of satellite positions
    :param beam_centers: (3, n_beams) array of beam center positions
    :return: (n_antenna_x*n_antenna_y*n_beams, n_beams) complex block diagonal matrix of normalized analog precoder
    """
    config = params.read_params()
    n_beams = config["n_beams"]
    n_antenna_x = config["n_antenna_x"]
    n_antenna_y = config["n_antenna_y"]

    # initialize precoder
    precoder = np.zeros([n_antenna_x * n_antenna_y * n_beams, n_beams], dtype=complex)

    # get angles between beam centers and satellite position
    phi, theta, beam_center_t = utils.get_angles_to_satellite(satellite_pos, beam_centers)
    Phi_x = -np.cos(phi) * np.sin(theta)
    Phi_y = -np.sin(phi) * np.sin(theta)
    # get array steering matrix
    a = utils.array_steering_matrix(Phi_x, Phi_y)  # (n_antenna_x*n_beams_x, n_antenna_y*n_beams_y, n_beams)

    # reshape into block-diagonal matrix
    for i_beam in range(n_beams):
        beam_start = i_beam * n_antenna_x * n_antenna_y
        beam_stop = beam_start + n_antenna_x * n_antenna_y
        precoder[beam_start:beam_stop, i_beam] = utils.get_beam_coefficients(a[:, :, i_beam], i_beam)
    return precoder / np.sqrt(n_antenna_x * n_antenna_y)


def get_Rician_fading_coefficient(n_user):
    """
    Calculate Rician fading factor for each user.
    :param n_user: number of users
    :return: g (n_user, 1)complex Rician fading coefficient for each user
    """
    config = params.read_params()
    rician_k = config["rician_k"]

    mu = np.sqrt(rician_k / (2*(rician_k+1)))
    sigma = np.sqrt(1 / (2*(rician_k+1)))
    g = np.random.normal(mu, sigma, size=(n_user, 1)) + 1j*np.random.normal(mu, sigma, size=(n_user, 1))
    return g  # (n_user, )


def get_satellite_Doppler_shift():
    """
    Calculates the Doppler shift from satellite movement. (Same for all users, as it only depends on satellite speed.)
    :return: maximum Doppler shift resulting from satellite movement
    """
    config = params.read_params()
    v_sat = config["v_satellite"]
    SPEED_OF_LIGHT = config["SPEED_OF_LIGHT"]
    center_freq = config["center_frequency"]

    doppler_shift = v_sat / SPEED_OF_LIGHT * center_freq
    return doppler_shift


def get_satellite_delay_phase_shift(user_pos, satellite_pos):
    """
    Calculates the phase shift stemming from the transmission delay between the user and satellite position for all
    users in each sub-band.
    :param user_pos: (3, n_user) user positions in Cartesian coordinates
    :param satellite_pos: (3, 1) current satellite position in Cartesian coordinates
    :return: (n_user,) complex phase shifts for all users
    """
    config = params.read_params()
    SPEED_OF_LIGHT = config["SPEED_OF_LIGHT"]
    center_freq = config["center_frequency"]

    distance_m = utils.calculate_user_satellite_distance(user_pos, satellite_pos)
    delay = distance_m/SPEED_OF_LIGHT
    phase_shift = np.exp(-2j*np.pi*delay[:, np.newaxis]*center_freq)
    return phase_shift


def get_effective_channel(loss_db, precoder_analog, i_sat_pos, user_pos, n_user, i_frame):
    """
    create user channels
    :param loss_db: (n_user,) loss due to FSPL and atmospheric attenuation in dB
    :param precoder_analog: (n_antenna_x*n_antenna_y*n_beams, n_beams)complex
    :param i_sat_pos: (3,) satellite position in Cartesian coordinates in meter
    :param user_pos: (3, n_user) user positions in Cartesian coordinates in meter
    :param n_user: number of users
    :param i_frame: frame index - used to calculate Doppler shift
    :return: effective_channel (n_user, n_beams)complex effective transmission channel including Rician fading, path
                                                          loss, array steering vector and beam steering
    :return: macro_channel (n_user, n_beams)complex macroscopic channel including beam steering, array steering and
                                                    path loss, but without Rician fading
    :return: beam_gain (n_user, n_beams)complex gain observed by each user from each beam
    """

    config = params.read_params()
    n_beams = config["n_beams"]
    t_frame = config["t_frame"]
    antenna_gain = config["antenna_gain_dB"]
    tx_power_W = config["transmit_power_W"]

    macro_loss = np.sqrt(tx_power_W * utils.from_dB(antenna_gain - loss_db))  # (n_user,)
    macro_loss = macro_loss[:, np.newaxis]  # (n_user, 1)

    # get array steering vector for each user
    a = get_array_steering_vector(i_sat_pos, user_pos)  # (n_user, n_ant_total)

    # get Rician fading coefficients for each user
    rician_fading = get_Rician_fading_coefficient(n_user)  # (n_user, 1)

    # add constant phase shift to Rician fading for each user in each sub-band (n_user, )
    doppler_phase_shift = np.exp(-2j * np.pi * get_satellite_Doppler_shift() * i_frame * t_frame)
    delay_phase_shift = get_satellite_delay_phase_shift(user_pos, i_sat_pos)
    constant_phase_shift = doppler_phase_shift * delay_phase_shift  # (n_user, )
    rician_fading = rician_fading * constant_phase_shift

    # combine array steering vector and analog precoder (for efficiency-gets rid of individual antenna element entries)
    beam_gain = np.empty([n_user, n_beams], dtype=complex)
    for i_user in range(n_user):
        beam_gain[i_user, :] = a[i_user, :] @ precoder_analog

    # get effective (channel + analog precoder) channel for each user
    effective_channel = macro_loss * rician_fading * beam_gain  # (n_user, n_beam)
    macro_channel = macro_loss * beam_gain  # (n_user, n_beam)

    return effective_channel, macro_channel, beam_gain
