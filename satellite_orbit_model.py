import numpy as np


def satellite_orbit_model(network_geometry, frame_index: int):
    sat_pos = network_geometry.get_satellite_pos()
    sat_pos[:, 38537] = np.array([0, 0, 600e3])
    return sat_pos[:, frame_index]
