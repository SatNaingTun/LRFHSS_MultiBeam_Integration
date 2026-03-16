def coverage_footprint(network_geometry, user_count: int):
    user_pos = network_geometry.get_user_position(user_count)
    beam_centers = network_geometry.hex_grid_centers_two_rings()
    return user_pos, beam_centers
