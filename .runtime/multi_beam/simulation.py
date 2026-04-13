import json
import numpy as np

import channel
import networkGeometry
import params
import utils


def run_simulations_and_save_results_macro():
    """
    Run simulation for map plotting and save results.
    :return:
    """
    result_folder = "results/"
    result_file = "macro_no_Rician"
    # update parameter file and read in parameters
    r_footprint = 100e3
    params.update_param_file(r_footprint)  # make sure parameters are consistent
    config = params.read_params()  # load parameters from parameter file
    ant_gain_dB = config["antenna_gain_dB"]

    # create positions
    sat_pos = networkGeometry.get_satellite_pos()  # (3, n_frame_total) positions with elevation 0deg to 180deg
    sat_pos[:, 38537] = np.array([0, 0, 600e3])  # set 90 degree position to exactly 90 degree elevation angle
    user_pos = networkGeometry.get_grid_positions(500)  # (3, n_user)
    n_user = np.size(user_pos, axis=1)
    # set beam centers
    beam_centers = networkGeometry.hex_grid_centers_two_rings()

    frames = np.array([38537, 33090, 23932])  # [90 deg, 55 deg, 25 deg]
    for i_frame in frames:
        i_sat_pos = sat_pos[:, i_frame]
        # print elevation angle to center position
        elevation_angle = utils.get_elevation_angle_from_center(i_sat_pos[0], i_sat_pos[2]) / np.pi * 180
        print(f'elevation angle: {elevation_angle} deg')

        # calculate macroscopic fading for each user in this frame (free space path loss + atmospheric gases macro_loss)
        loss_dB = channel.path_loss(user_pos, i_sat_pos)  # (n_user, )

        # set analog precoder (n_antenna_x*n_antenna_y, n_beams)
        precoder_analog = channel.fixed_beam_steering(i_sat_pos, beam_centers)

        # create user channels
        _, macro_channel, beam_gain = channel.get_effective_channel(loss_dB, precoder_analog, i_sat_pos, user_pos,
                                                                    n_user, i_frame)
        # allocate users to beams with strongest received power
        fading = np.abs(macro_channel) ** 2
        _, beam_index = np.where(np.transpose((np.transpose(fading) == fading.max(axis=1))))

        sinr, snr, beam_gain_dB = calculate_simulation_result(macro_channel, n_user, beam_index, beam_gain, ant_gain_dB)

        # save results
        result = {
            "user_positions": user_pos.tolist(),
            "n_user": n_user,
            "satellite_position": i_sat_pos.tolist(),
            "snr": snr.tolist(),
            "sinr": sinr.tolist(),
            "beam_index": beam_index.tolist(),
            "center_beam_gain_dB": beam_gain_dB.tolist(),
            "beam_centers": beam_centers.tolist(),
            "r_footprint": r_footprint,
            "elevation_angle": elevation_angle,
        }
        result_file_name = f'{result_folder}/{result_file}{i_frame}_{int(r_footprint/1e3)}km.json'
        with open(result_file_name, 'w') as f:
            json.dump(result, f)


def run_simulations_and_save_results_rician():
    """
    Run simulations for ECDF plots with Rician fading and save results.
    :return:
    """
    result_folder = "results/"
    result_file = "macro_with_Rician"
    r_footprint = np.array([200e3, 100e3, 50e3, 5e3])

    # update parameter file and read in parameters
    params.update_param_file(100e3)  # make sure parameters are consistent
    config = params.read_params()  # load parameters from parameter file
    ant_gain_dB = config["antenna_gain_dB"]

    # create satellite positions
    sat_pos = networkGeometry.get_satellite_pos()  # (3, n_frame_total) positions with elevation 0deg to 180deg
    sat_pos[:, 38537] = np.array([0, 0, 600e3])
    frames = np.array([38537, 33090, 23932])  # [90 deg, 55 deg, 25 deg]

    for i_footprint in r_footprint:
        # update parameter file
        params.update_param_file(i_footprint)  # make sure parameters are consistent
        user_pos = networkGeometry.get_user_position(100000)  # (3, n_user)
        n_user = np.size(user_pos, axis=1)
        beam_centers = networkGeometry.hex_grid_centers_two_rings()

        for i_frame in frames:
            i_sat_pos = sat_pos[:, i_frame]
            # print elevation angle to center position
            elevation_angle = utils.get_elevation_angle_from_center(i_sat_pos[0], i_sat_pos[2]) / np.pi * 180
            print(f'elevation angle: {elevation_angle} deg')

            # calculate macroscopic fading for each user (free space path loss + atmospheric gases macro_loss)
            loss_dB = channel.path_loss(user_pos, i_sat_pos)  # (n_user, )

            # set analog precoder (n_antenna_x*n_antenna_y, n_beams)
            precoder_analog = channel.fixed_beam_steering(i_sat_pos, beam_centers)

            # create user channels
            micro_channel, macro_channel, beam_gain = channel.get_effective_channel(loss_dB, precoder_analog, i_sat_pos,
                                                                                    user_pos, n_user, i_frame)
            # allocate users to beams with strongest received power
            fading = np.abs(macro_channel) ** 2
            _, beam_index = np.where(np.transpose((np.transpose(fading) == fading.max(axis=1))))

            sinr, snr, bGain_dB = calculate_simulation_result(micro_channel, n_user, beam_index, beam_gain, ant_gain_dB)

            # save results
            result = {
                "user_positions": user_pos.tolist(),
                "n_user": n_user,
                "satellite_position": i_sat_pos.tolist(),
                "snr": snr.tolist(),
                "sinr": sinr.tolist(),
                "beam_index": beam_index.tolist(),
                "center_beam_gain_dB": bGain_dB.tolist(),
                "beam_centers": beam_centers.tolist(),
                "r_footprint": i_footprint,
                "elevation_angle": elevation_angle,
            }
            result_file_name = f'{result_folder}/{result_file}{i_frame}_{int(i_footprint/1e3)}km.json'
            with open(result_file_name, 'w') as f:
                json.dump(result, f)


def calculate_simulation_result(channel_, n_user, beam_index, beam_gain, ant_gain_db):
    """
    Calculate SNR and SINR results.
    :param channel_: macro or micro channel
    :param n_user: number of users in simulation
    :param beam_index: index of beam serving each user
    :param beam_gain: beam gain per beam and user
    :param ant_gain_db: fixed antenna gain
    :return: sinr, snr, center_beam_gain_dB array with simulation results per user position
    """
    rec_power = np.abs(channel_) ** 2
    desired_power = rec_power[range(n_user), beam_index]
    receive_power = np.sum(rec_power[:, :], axis=1)
    interference_power = receive_power - desired_power
    noise = params.get_noise_power()
    sinr = utils.to_dB(desired_power / (interference_power + noise))
    snr = utils.to_dB(desired_power / noise)
    center_beam_gain_dB = utils.to_dB(np.abs(beam_gain[range(n_user), 9]) ** 2) + ant_gain_db
    return sinr, snr, center_beam_gain_dB


if __name__ == "__main__":
    run_simulations_and_save_results_rician()
    run_simulations_and_save_results_macro()
