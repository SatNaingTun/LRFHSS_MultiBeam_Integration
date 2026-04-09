import math

import numpy as np


def generate_iot_nodes(node_count: int):
    return list(range(node_count))


def assign_lrfhss_packets(nodes: list[int]):
    return len(nodes)


def transmit_fragments(packet_count: int, visible: bool):
    return packet_count if visible else 0


def detect_collisions(decoded_metrics: dict):
    return int(decoded_metrics["collided"])


def baseline_packet_decoding(LoRaNetwork, node_count: int, demods: int, use_earlydecode: bool, use_earlydrop: bool):
    if node_count <= 0 or demods <= 0:
        return {
            "tracked_txs": 0,
            "decoded_headers": 0,
            "decoded_header_payloads": 0,
            "decoded_bytes": 0,
            "collided": 0,
        }

    network = LoRaNetwork(
        numNodes=node_count,
        familyname="driver",
        numOCW=7,
        numOBW=280,
        numGrids=8,
        CR=1,
        timeGranularity=6,
        freqGranularity=25,
        simTime=228,
        numDecoders=demods,
        use_earlydecode=use_earlydecode,
        use_earlydrop=use_earlydrop,
        use_headerdrop=False,
        collision_method="strict",
    )
    network.run(False, False)

    return {
        "tracked_txs": int(network.get_tracked_txs()),
        "decoded_headers": int(network.get_decoded_hdr()),
        "decoded_header_payloads": int(network.get_decoded_hrd_pld()),
        "decoded_bytes": int(network.get_decoded_bytes()),
        "collided": int(network.get_collided_hdr_pld()),
    }


def summarize_stats(values: list[float]) -> dict:
    arr = np.array(values, dtype=float)
    if arr.size == 0:
        return {"mean": 0.0, "variance": 0.0, "ci95_low": 0.0, "ci95_high": 0.0}
    mean_val = float(np.mean(arr))
    variance_val = float(np.var(arr, ddof=1)) if arr.size > 1 else 0.0
    std_val = float(np.std(arr, ddof=1)) if arr.size > 1 else 0.0
    ci_half = float(1.96 * std_val / math.sqrt(arr.size)) if arr.size > 1 else 0.0
    return {
        "mean": mean_val,
        "variance": variance_val,
        "ci95_low": float(mean_val - ci_half),
        "ci95_high": float(mean_val + ci_half),
    }
