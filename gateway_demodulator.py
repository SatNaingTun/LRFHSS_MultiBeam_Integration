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


def _empty_result(node_count: int):
    return {
        "num_nodes": int(node_count),
        "tracked_txs": 0,
        "header_drop_packets": 0,
        "decoded_bytes": 0,
        "decoded_hrd_pld": 0,
        "decoded_hdr": 0,
        "decodable_pld": 0,
        "collided_hdr_pld": 0,
    }


def gateway_demodulator(LoRaNetwork, node_count: int, decoder_count: int):
    if node_count <= 0:
        return _empty_result(node_count)

    net = LoRaNetwork(
        numNodes=node_count,
        familyname=BASELINE_CONFIG["familyname"],
        numOCW=BASELINE_CONFIG["numOCW"],
        numOBW=BASELINE_CONFIG["numOBW"],
        numGrids=BASELINE_CONFIG["numGrids"],
        CR=BASELINE_CONFIG["CR"],
        timeGranularity=BASELINE_CONFIG["timeGranularity"],
        freqGranularity=BASELINE_CONFIG["freqGranularity"],
        simTime=BASELINE_CONFIG["simTime"],
        numDecoders=decoder_count,
        use_earlydecode=BASELINE_CONFIG["use_earlydecode"],
        use_earlydrop=BASELINE_CONFIG["use_earlydrop"],
        use_headerdrop=BASELINE_CONFIG["use_headerdrop"],
        collision_method=BASELINE_CONFIG["collision_method"],
    )
    net.run(BASELINE_CONFIG["power"], BASELINE_CONFIG["dynamic"])

    return {
        "num_nodes": int(node_count),
        "tracked_txs": int(net.get_tracked_txs()),
        "header_drop_packets": int(net.get_header_drop_packets()),
        "decoded_bytes": int(net.get_decoded_bytes()),
        "decoded_hrd_pld": int(net.get_decoded_hrd_pld()),
        "decoded_hdr": int(net.get_decoded_hdr()),
        "decodable_pld": int(net.get_decodable_pld()),
        "collided_hdr_pld": int(net.get_collided_hdr_pld()),
    }
