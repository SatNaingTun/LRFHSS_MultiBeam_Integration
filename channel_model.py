import numpy as np


def channel_model(channel_mod, i_sat_pos, user_pos, beam_centers, n_user: int, frame_index: int, n_beams: int):
    loss_dB = channel_mod.path_loss(user_pos, i_sat_pos)
    precoder_analog = channel_mod.fixed_beam_steering(i_sat_pos, beam_centers)
    _, macro_channel, _ = channel_mod.get_effective_channel(
        loss_dB,
        precoder_analog,
        i_sat_pos,
        user_pos,
        n_user,
        frame_index,
    )

    fading = np.abs(macro_channel) ** 2
    _, beam_index = np.where(np.transpose((np.transpose(fading) == fading.max(axis=1))))
    beam_node_counts = np.bincount(beam_index, minlength=n_beams)
    return beam_node_counts
