import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def _safe_ratio(num, den):
    return (num / den) if den else 0.0


def load_result(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def plot_frame_summary(data: dict, out_dir: Path):
    frames = data.get("frames", [])
    if not frames:
        return None

    x = [f["elevation_angle_deg"] for f in frames]
    decoded_ratio = [f.get("decoded_hrd_pld_ratio", 0.0) for f in frames]
    decoded_bytes = [f.get("total_decoded_bytes", 0) for f in frames]

    fig, ax1 = plt.subplots(figsize=(8, 5))
    ax1.plot(
        x,
        decoded_ratio,
        marker="o",
        linestyle="-",
        color="#0072B2",
        label="Decoded HDR+PLD Ratio",
    )
    ax1.set_xlabel("Elevation Angle (deg)")
    ax1.set_ylabel("Decoded HDR+PLD Ratio", color="#0072B2")
    ax1.tick_params(axis="y", labelcolor="#0072B2")
    ax1.grid(True, linestyle=":", alpha=0.5)

    ax2 = ax1.twinx()
    ax2.plot(
        x,
        decoded_bytes,
        marker="s",
        linestyle="--",
        color="#D55E00",
        label="Decoded Bytes",
    )
    ax2.set_ylabel("Decoded Bytes", color="#D55E00")
    ax2.tick_params(axis="y", labelcolor="#D55E00")

    fig.suptitle("Workflow Performance vs Elevation Angle")
    fig.tight_layout()

    out = out_dir / "frame_summary.png"
    fig.savefig(out, dpi=180)
    plt.close(fig)
    return out


def plot_frame_totals(data: dict, out_dir: Path):
    frames = data.get("frames", [])
    if not frames:
        return None

    labels = [f"{f['elevation_angle_deg']:.1f} deg" for f in frames]
    tracked = np.array([f.get("total_tracked_txs", 0) for f in frames])
    decoded = np.array([f.get("total_decoded_hrd_pld", 0) for f in frames])
    collided = np.array([f.get("total_collided_hdr_pld", 0) for f in frames])

    x = np.arange(len(labels))
    width = 0.26

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.bar(x - width, tracked, width, label="Tracked TXs", color="#4e79a7")
    ax.bar(x, decoded, width, label="Decoded HDR+PLD", color="#59a14f")
    ax.bar(x + width, collided, width, label="Collided HDR+PLD", color="#e15759")

    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Count")
    ax.set_title("Frame-Level Totals")
    ax.grid(True, axis="y", linestyle=":", alpha=0.5)
    ax.legend()

    fig.tight_layout()
    out = out_dir / "frame_totals.png"
    fig.savefig(out, dpi=180)
    plt.close(fig)
    return out


def plot_per_beam_heatmap(data: dict, out_dir: Path):
    frames = data.get("frames", [])
    if not frames:
        return None

    beam_ids = sorted([b["beam_id"] for b in frames[0].get("per_beam", [])])
    if not beam_ids:
        return None

    heat = []
    ylabels = []
    for frame in frames:
        per_beam = {b["beam_id"]: b for b in frame.get("per_beam", [])}
        row = []
        for bid in beam_ids:
            item = per_beam.get(bid, {})
            ratio = _safe_ratio(item.get("decoded_hrd_pld", 0), item.get("tracked_txs", 0))
            row.append(ratio)
        heat.append(row)
        ylabels.append(f"{frame['elevation_angle_deg']:.1f} deg")

    arr = np.array(heat)

    fig, ax = plt.subplots(figsize=(10, 4 + 0.3 * len(frames)))
    # 'cividis' is perceptually uniform and generally color-vision-deficiency friendly.
    im = ax.imshow(arr, aspect="auto", cmap="cividis", vmin=0.0, vmax=1.0)

    ax.set_xticks(np.arange(len(beam_ids)))
    ax.set_xticklabels([str(i) for i in beam_ids], rotation=0)
    ax.set_yticks(np.arange(len(ylabels)))
    ax.set_yticklabels(ylabels)
    ax.set_xlabel("Beam ID")
    ax.set_ylabel("Elevation Angle")
    ax.set_title("Per-Beam Decoded Ratio (decoded_hrd_pld / tracked_txs)")

    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label("Decoded Ratio")

    fig.tight_layout()
    out = out_dir / "per_beam_decoded_ratio_heatmap.png"
    fig.savefig(out, dpi=180)
    plt.close(fig)
    return out


def parse_args():
    parser = argparse.ArgumentParser(description="Plot workflow results from workflow_result.json")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("results/workflow_result.json"),
        help="Input JSON result file",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("results/plots"),
        help="Output directory for generated plots",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    data = load_result(args.input)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    outputs = [
        plot_frame_summary(data, args.output_dir),
        plot_frame_totals(data, args.output_dir),
        plot_per_beam_heatmap(data, args.output_dir),
    ]
    outputs = [p for p in outputs if p is not None]

    if not outputs:
        print("No plots generated: input has no frame data.")
        return

    print("Generated plots:")
    for p in outputs:
        print(p.resolve())


if __name__ == "__main__":
    main()
