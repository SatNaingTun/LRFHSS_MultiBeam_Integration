def performance_metrics(frame_index: int, elevation_angle_deg: float, per_beam: list[dict], total_nodes: int):
    total_tracked_txs = int(sum(item["tracked_txs"] for item in per_beam))
    total_decoded_hrd_pld = int(sum(item["decoded_hrd_pld"] for item in per_beam))
    total_decoded_bytes = int(sum(item["decoded_bytes"] for item in per_beam))
    total_collided_hdr_pld = int(sum(item["collided_hdr_pld"] for item in per_beam))

    return {
        "frame": int(frame_index),
        "elevation_angle_deg": float(elevation_angle_deg),
        "total_nodes": int(total_nodes),
        "total_tracked_txs": total_tracked_txs,
        "total_decoded_hrd_pld": total_decoded_hrd_pld,
        "total_decoded_bytes": total_decoded_bytes,
        "total_collided_hdr_pld": total_collided_hdr_pld,
        "decoded_hrd_pld_ratio": (total_decoded_hrd_pld / total_tracked_txs) if total_tracked_txs > 0 else 0.0,
        "per_beam": per_beam,
    }
