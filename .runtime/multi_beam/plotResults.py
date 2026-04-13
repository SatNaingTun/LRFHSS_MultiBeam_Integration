import astropy.units as u
import itur
import matplotlib.pyplot as plt
import numpy as np
import json

import channel
import networkGeometry
import params
import utils


def plot_macro_results():
    """
    Plot S(I)NR ECDFs for three elevation angles from saved simulation results.
    :return:
    """
    result_folder = "results"
    frames = np.array([38537, 33090, 23932])  # [90 deg, 55 deg, 25 deg]
    r_footprint = np.array([200, 100, 50, 5])
    colors_sinr = ['pink', 'lightcoral', 'indianred', 'maroon']
    colors_snr = ['paleturquoise', 'lightskyblue', 'steelblue', 'darkslategray']
    line_style = ['solid', (0, (3, 1)), (0, (5, 2)), (0, (7, 2, 2, 2))]

    for i_frame in frames:  # loop over elevation angles
        # prepare plot
        leg = list()
        plt.figure()
        plt.grid(True)
        plt.ylabel("ECDF")
        plt.ylim([0, 1])
        for i_footprint in range(len(r_footprint)):  # loop over different footprint sizes
            # load results
            result_file_name = f'{result_folder}/macro_with_Rician{i_frame}_{int(r_footprint[i_footprint])}km.json'
            with open(result_file_name, 'r') as f:
                result = json.load(f)
            sinr = result["sinr"]
            snr = result["snr"]
            # plot ECDFs
            utils.plot_ecdf_same_figure(sinr, colors_sinr[i_footprint], l_style=line_style[i_footprint])
            utils.plot_ecdf_same_figure(snr, colors_snr[i_footprint], l_style=line_style[i_footprint])
            leg.append(f'SINR {r_footprint[i_footprint]} km')
            leg.append(f'SNR {r_footprint[i_footprint]} km')
        # label plot
        plt.legend(leg, loc='best')
        plt.xlim([-15, 10])
        plt.xlabel('S(I)NR (dB)')
        sat_pos = result["satellite_position"]
        plt.title(f'elevation angle {utils.get_elevation_angle_from_center(sat_pos[0], sat_pos[2])/np.pi*180}deg')


def plot_result_maps():
    """
    Plot beam gain, cell association, SNR, and SINR maps from saved results.
    :return:
    """
    result_folder = "results"
    frames = np.array([38537, 33090, 23932])  # [90 deg, 55 deg, 25 deg]
    r_footprint = 100e3
    n_beams = 19

    for i_frame in frames:  # loop over elevation angles to plot
        # load results
        result_file_name = f'{result_folder}/macro_no_Rician{i_frame}_{int(r_footprint/1000)}km.json'
        with open(result_file_name, 'r') as f:
            result = json.load(f)
        user_pos = np.array(result["user_positions"])
        snr = result["snr"]
        sinr = result["sinr"]
        center_beam_gain_dB = result["center_beam_gain_dB"]
        beam_index = result["beam_index"]
        beam_centers = np.array(result["beam_centers"])

        # plot SNR and SINR
        x_ticks = np.linspace(-15, 10, 6)
        plot_path_loss_map(user_pos, np.maximum(-15, sinr), 'SINR (dB)', -15, 10, x_ticks, r_footprint)
        plot_path_loss_map(user_pos, np.maximum(-15, snr), 'SNR (dB)', -15, 10, x_ticks, r_footprint)
        # plot beam gain map
        x_ticks = np.array([-40, -25, -10, 5, 20, 35, 50])
        plot_path_loss_map(user_pos, np.maximum(-40, center_beam_gain_dB), 'center beam gain (dB)', -40, 50, x_ticks,
                           r_footprint)
        # plot cell association
        plt.figure()
        plt.scatter(beam_centers[0, :]/1000, beam_centers[1, :]/1000, c=np.arange(0, n_beams), cmap='tab20', marker='d',
                    s=100)
        cbar = plt.colorbar(ticks=np.arange(0, n_beams))
        plt.clim(0, n_beams-1)  # this is necessary to match the colors of users to beams
        plt.scatter(user_pos[0, :]/1000, user_pos[1, :]/1000, c=beam_index, cmap='tab20', marker='H', s=10)
        cbar.set_label("beam index")
        plt.xlabel('x (km)')
        plt.ylabel('y (km)')
        plt.xlim([-r_footprint/1000, r_footprint/1000])
        plt.ylim([-r_footprint/1000, r_footprint/1000])


def plot_path_loss_map(user_pos, loss_dB, label, min_lim, max_lim, xticks, r_footprint):
    fig = plt.figure()
    levels = np.linspace(min_lim, max_lim, 250)
    plt.tricontourf(user_pos[0, :]/1000, user_pos[1, :]/1000, loss_dB, levels=levels, cmap='viridis')
    cbar = plt.colorbar(ticks=xticks)
    cbar.set_label(label)
    plt.clim(min_lim, max_lim)
    plt.xlabel('x (km)')
    plt.ylabel('y (km)')
    plt.xlim([-r_footprint/1000, r_footprint/1000])
    plt.ylim([-r_footprint/1000, r_footprint/1000])
    return fig, cbar


def path_loss_analysis():
    # plot path loss over elevation angles and plot path loss ECDF for different angles
    n_user = 10000

    config = params.read_params()
    frequency_Hz = config["center_frequency"]
    f = frequency_Hz * 1e-9 * u.GHz
    speed_of_light = config["SPEED_OF_LIGHT"]
    p = config["p"]
    D = config["D"] * u.m
    latitude = config["latitude_center"]
    longitude = config["longitude_center"]

    # generate positions
    user_pos = networkGeometry.get_user_position(n_user)
    sat_pos = networkGeometry.get_satellite_pos()
    eps = utils.get_elevation_angle_from_center(sat_pos[0, 12534:-12534], sat_pos[2, 12534:-12534])/np.pi*180
    # plot path loss over elevation angle
    fig = plt.figure()
    ax = fig.add_subplot()

    # calculate free space path loss
    distance_m = utils.calculate_user_satellite_distance(sat_pos[:, 12534:-12534], np.zeros(3))
    l_fspl = utils.to_dB((4*np.pi*distance_m*frequency_Hz/speed_of_light)**2)
    # calculate atmospheric loss
    elevation_angle = np.empty_like(eps)
    elevation_angle[eps >= 90] = 180-eps[eps >= 90]
    elevation_angle[eps < 90] = eps[eps < 90]
    l_atmospheric_dB = itur.atmospheric_attenuation_slant_path(latitude, longitude, f, elevation_angle, p, D)
    # combine free space and atmospheric losses
    path_loss = l_fspl + np.array(l_atmospheric_dB)
    ax.plot(eps, path_loss)
    plt.grid(True)
    plt.xlim([0, 180])
    plt.ylim([185, 220])
    plt.xlabel('elevation angle (degree)')
    plt.xticks([0, 15, 30, 45, 60, 75, 90, 105, 120, 135, 150, 165, 180])
    plt.yticks([185, 195, 205, 215])
    plt.ylabel('path loss (dB)')

    # calculate macroscopic path loss
    path_loss_dB = channel.path_loss(user_pos, sat_pos[:, 38537])
    utils.plot_ecdf(path_loss_dB, "black", l_style=(0, (3, 1)))
    path_loss_dB = channel.path_loss(user_pos, sat_pos[:, 37140])
    utils.plot_ecdf_same_figure(path_loss_dB, "dimgray", l_style=(0, (4, 1)))
    path_loss_dB = channel.path_loss(user_pos, sat_pos[:, 35665])
    utils.plot_ecdf_same_figure(path_loss_dB, "darkgray", l_style='dashed')
    path_loss_dB = channel.path_loss(user_pos, sat_pos[:, 34018])
    utils.plot_ecdf_same_figure(path_loss_dB, "lightgray", l_style=(0, (6, 1, 2, 1)))
    path_loss_dB = channel.path_loss(user_pos, sat_pos[:, 32064])
    utils.plot_ecdf_same_figure(path_loss_dB, "powderblue", l_style=(0, (5, 2)))
    path_loss_dB = channel.path_loss(user_pos, sat_pos[:, 29583])
    utils.plot_ecdf_same_figure(path_loss_dB, "mediumturquoise", l_style=(0, (6, 2, 2, 2)))
    path_loss_dB = channel.path_loss(user_pos, sat_pos[:, 26185])
    utils.plot_ecdf_same_figure(path_loss_dB, "lightseagreen", l_style=(0, (8, 2, 2, 2)))
    path_loss_dB = channel.path_loss(user_pos, sat_pos[:, 21130])
    utils.plot_ecdf_same_figure(path_loss_dB, "cadetblue", l_style=(0, (10, 2, 4, 2)))
    path_loss_dB = channel.path_loss(user_pos, sat_pos[:, 13052])
    utils.plot_ecdf_same_figure(path_loss_dB, "teal")
    plt.legend(["90 deg", "80 deg", "70 deg", "60 deg", "50 deg", "40 deg", "30 deg", "20 deg", "10 deg"],
               loc="lower right")
    plt.xlim([180, 220])
    plt.xlabel("path loss (dB)")
    plt.xticks([180, 185, 190, 195, 200, 205, 210, 215, 220])


def main():
    # plot Figure 5 - atmospheric gases attenuation over elevation angle
    channel.atmospheric_gases_plot()
    # plot Figure 6 and Figure 7 - path loss over elevation and path loss ECDFs
    path_loss_analysis()
    # plot Figure 9 - S(I)NR ECDFs
    plot_macro_results()
    # plot Figure 10 - beam gain, cell association, SNR, and SINR maps
    plot_result_maps()
    plt.show()


if __name__ == '__main__':
    main()
