import numpy as np


def channel_model(channel_module, satellite_position, user_positions, beam_centers, user_count: int, frame_index: int, beam_count: int):
    loss_db = channel_module.path_loss(user_positions, satellite_position)
    analog_precoder = channel_module.fixed_beam_steering(satellite_position, beam_centers)
    _, macro_channel, _ = channel_module.get_effective_channel(
        loss_db,
        analog_precoder,
        satellite_position,
        user_positions,
        user_count,
        frame_index,
    )

    fading = np.abs(macro_channel) ** 2
    _, beam_index = np.where(np.transpose((np.transpose(fading) == fading.max(axis=1))))
    beam_node_counts = np.bincount(beam_index, minlength=beam_count)
    return beam_node_counts
