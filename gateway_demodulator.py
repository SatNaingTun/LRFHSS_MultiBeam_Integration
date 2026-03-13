BASELINE_CONFIG = {
    "simTime": 228,
    "numOCW": 1,
    "numOBW": 280,
    "numGrids": 8,
    "timeGranularity": 6,
    "freqGranularity": 25,
    "CR": 1,
    "use_earlydecode": False,
    "use_earlydrop": False,
    "use_headerdrop": False,
    "familyname": "driver",
    "power": False,
    "dynamic": False,
    "collision_method": "strict",
}


def _empty_result(num_nodes: int):
    return {
        "num_nodes": int(num_nodes),
        "tracked_txs": 0,
        "header_drop_packets": 0,
        "decoded_bytes": 0,
        "decoded_hrd_pld": 0,
        "decoded_hdr": 0,
        "decodable_pld": 0,
        "collided_hdr_pld": 0,
    }


def gateway_demodulator(LoRaNetwork, num_nodes: int, num_decoders: int):
    if num_nodes <= 0:
        return _empty_result(num_nodes)

    net = LoRaNetwork(
        num_nodes,
        BASELINE_CONFIG["familyname"],
        BASELINE_CONFIG["numOCW"],
        BASELINE_CONFIG["numOBW"],
        BASELINE_CONFIG["numGrids"],
        BASELINE_CONFIG["CR"],
        BASELINE_CONFIG["timeGranularity"],
        BASELINE_CONFIG["freqGranularity"],
        BASELINE_CONFIG["simTime"],
        num_decoders,
        BASELINE_CONFIG["use_earlydecode"],
        BASELINE_CONFIG["use_earlydrop"],
        BASELINE_CONFIG["use_headerdrop"],
        BASELINE_CONFIG["collision_method"],
    )
    net.run(BASELINE_CONFIG["power"], BASELINE_CONFIG["dynamic"])

    return {
        "num_nodes": int(num_nodes),
        "tracked_txs": int(net.get_tracked_txs()),
        "header_drop_packets": int(net.get_header_drop_packets()),
        "decoded_bytes": int(net.get_decoded_bytes()),
        "decoded_hrd_pld": int(net.get_decoded_hrd_pld()),
        "decoded_hdr": int(net.get_decoded_hdr()),
        "decodable_pld": int(net.get_decodable_pld()),
        "collided_hdr_pld": int(net.get_collided_hdr_pld()),
    }
