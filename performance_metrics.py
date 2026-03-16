def performance_metrics(frame_index: int, elevation_angle_deg: float, per_beam_metrics: list[dict], total_nodes: int):
    total_tracked_txs = int(sum(beam_metrics["tracked_txs"] for beam_metrics in per_beam_metrics))
    total_decoded_hrd_pld = int(sum(beam_metrics["decoded_hrd_pld"] for beam_metrics in per_beam_metrics))
    total_decoded_bytes = int(sum(beam_metrics["decoded_bytes"] for beam_metrics in per_beam_metrics))
    total_collided_hdr_pld = int(sum(beam_metrics["collided_hdr_pld"] for beam_metrics in per_beam_metrics))

    return {
        "frame": int(frame_index),
        "elevation_angle_deg": float(elevation_angle_deg),
        "total_nodes": int(total_nodes),
        "total_tracked_txs": total_tracked_txs,
        "total_decoded_hrd_pld": total_decoded_hrd_pld,
        "total_decoded_bytes": total_decoded_bytes,
        "total_collided_hdr_pld": total_collided_hdr_pld,
        "decoded_hrd_pld_ratio": (total_decoded_hrd_pld / total_tracked_txs) if total_tracked_txs > 0 else 0.0,
        "per_beam": per_beam_metrics,
    }
