import argparse
import csv
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path

import numpy as np

INTEGRATION_ROOT = Path(__file__).resolve().parents[1]
if str(INTEGRATION_ROOT) not in sys.path:
    sys.path.insert(0, str(INTEGRATION_ROOT))

from multi_beam_connector import load_multi_beam_modules

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency
    raise ModuleNotFoundError("matplotlib is required. Install with: pip install matplotlib") from exc

try:
    from tqdm import tqdm
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    tqdm = None


@contextmanager
def _pushd(path: Path):
    prev = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(prev)


def _ecdf_xy(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    x = np.sort(values.astype(float))
    n = x.size
    if n == 0:
        return np.array([], dtype=float), np.array([], dtype=float)
    y = np.arange(1, n + 1, dtype=float) / float(n)
    return x, y


def _parse_args() -> argparse.Namespace:
    snt_root = INTEGRATION_ROOT.parent

    parser = argparse.ArgumentParser(
        description="Standalone elevation-angle reproduction script (paper-style ECDF for SNR/SINR)."
    )
    parser.add_argument("--multi-beam-root", type=Path, default=snt_root / "Multi-Beam-LEO-Framework")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=INTEGRATION_ROOT / "results" / "lrfhss_communication" / "elevation_angle",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--n-user", type=int, default=100000)
    return parser.parse_args()


def run_elevation_angle_study(
    multi_beam_root: Path,
    output_dir: Path,
    seed: int = 42,
    n_user: int = 100000,
) -> dict:
    np.random.seed(int(seed))
    output_dir.mkdir(parents=True, exist_ok=True)

    with _pushd(multi_beam_root):
        channel, network_geometry, params_mod, _, simulation = load_multi_beam_modules(multi_beam_root)

        footprint_km = [200, 100, 50, 5]
        footprint_m = [km * 1e3 for km in footprint_km]
        frames_by_elevation = {90: 38537, 55: 33090, 25: 23932}

        params_mod.update_param_file(100e3)
        ant_gain_db = float(params_mod.read_params()["antenna_gain_dB"])

        sat_pos = network_geometry.get_satellite_pos()
        sat_pos[:, 38537] = np.array([0.0, 0.0, 600e3], dtype=float)

        curves: dict[tuple[int, int], dict[str, np.ndarray]] = {}
        metrics_rows: list[dict] = []

        footprint_iter = zip(footprint_km, footprint_m)
        if tqdm is not None:
            footprint_iter = tqdm(list(footprint_iter), desc="Footprints", unit="fp")

        for f_km, f_m in footprint_iter:
            params_mod.update_param_file(f_m)
            user_pos = network_geometry.get_user_position(int(n_user))
            n_user_actual = int(user_pos.shape[1])
            beam_centers = network_geometry.hex_grid_centers_two_rings()

            elev_iter = frames_by_elevation.items()
            if tqdm is not None:
                elev_iter = tqdm(list(elev_iter), desc=f"Elevations@{f_km}km", unit="ang", leave=False)

            for elev_deg, frame_idx in elev_iter:
                i_sat_pos = sat_pos[:, int(frame_idx)]
                loss_db = channel.path_loss(user_pos, i_sat_pos)
                precoder_analog = channel.fixed_beam_steering(i_sat_pos, beam_centers)
                micro_channel, macro_channel, beam_gain = channel.get_effective_channel(
                    loss_db,
                    precoder_analog,
                    i_sat_pos,
                    user_pos,
                    n_user_actual,
                    int(frame_idx),
                )
                fading = np.abs(macro_channel) ** 2
                beam_index = np.argmax(fading, axis=1)
                sinr_db, snr_db, _ = simulation.calculate_simulation_result(
                    micro_channel,
                    n_user_actual,
                    beam_index,
                    beam_gain,
                    ant_gain_db,
                )
                sinr_db = np.array(sinr_db, dtype=float)
                snr_db = np.array(snr_db, dtype=float)
                curves[(elev_deg, f_km)] = {"snr": snr_db, "sinr": sinr_db}

                metrics_rows.append(
                    {
                        "elevation_deg": elev_deg,
                        "footprint_km": f_km,
                        "n_user": n_user_actual,
                        "snr_mean_db": float(np.mean(snr_db)),
                        "snr_p50_db": float(np.percentile(snr_db, 50)),
                        "snr_p90_db": float(np.percentile(snr_db, 90)),
                        "sinr_mean_db": float(np.mean(sinr_db)),
                        "sinr_p50_db": float(np.percentile(sinr_db, 50)),
                        "sinr_p90_db": float(np.percentile(sinr_db, 90)),
                    }
                )

    colors = {200: "#f2a7b8", 100: "#6ec5ff", 50: "#2f7ebc", 5: "#8b1a1a"}
    fig, axes = plt.subplots(1, 3, figsize=(16, 4.3), sharey=True)

    for ax, elev_deg in zip(axes, [90, 55, 25]):
        for f_km in [200, 100, 50, 5]:
            series = curves[(elev_deg, f_km)]
            xs_snr, ys_snr = _ecdf_xy(series["snr"])
            xs_sinr, ys_sinr = _ecdf_xy(series["sinr"])
            ax.plot(xs_snr, ys_snr, color=colors[f_km], linewidth=2.0, linestyle="-", label=f"{f_km} km SNR")
            ax.plot(xs_sinr, ys_sinr, color=colors[f_km], linewidth=2.0, linestyle="--", label=f"{f_km} km SINR")
        ax.set_title(f"({chr(96 + [90, 55, 25].index(elev_deg) + 1)}) {elev_deg}°", fontsize=13, fontweight="bold")
        ax.set_xlabel("S(I)NR (dB)", fontsize=12)
        ax.grid(True, alpha=0.35)
        ax.set_ylim(0.0, 1.02)
        ax.set_xlim(-15, 10)
        ax.legend(fontsize=8, loc="lower right", framealpha=0.9)

    axes[0].set_ylabel("ECDF", fontsize=12)
    fig.suptitle("Impact of elevation angle on SNR/SINR ECDF", fontsize=15)
    fig.tight_layout(rect=[0, 0, 1, 0.94])

    plot_path = output_dir / "elevation_angle_ecdf_snr_sinr.png"
    fig.savefig(plot_path, dpi=220)
    plt.close(fig)

    metrics_csv = output_dir / "elevation_angle_metrics.csv"
    with metrics_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "elevation_deg",
                "footprint_km",
                "n_user",
                "snr_mean_db",
                "snr_p50_db",
                "snr_p90_db",
                "sinr_mean_db",
                "sinr_p50_db",
                "sinr_p90_db",
            ],
        )
        writer.writeheader()
        writer.writerows(metrics_rows)

    summary = {
        "multi_beam_root": str(multi_beam_root.resolve()),
        "output_dir": str(output_dir.resolve()),
        "seed": int(seed),
        "n_user": int(n_user),
        "elevation_deg": [90, 55, 25],
        "footprint_km": [200, 100, 50, 5],
        "plot": str(plot_path.resolve()),
        "metrics_csv": str(metrics_csv.resolve()),
    }
    summary_path = output_dir / "elevation_angle_summary.json"
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    return summary


def main() -> None:
    args = _parse_args()
    summary = run_elevation_angle_study(
        multi_beam_root=args.multi_beam_root,
        output_dir=args.output_dir,
        seed=args.seed,
        n_user=args.n_user,
    )
    print("Elevation-angle study completed.")
    print(f"Plot:        {summary['plot']}")
    print(f"Metrics CSV: {summary['metrics_csv']}")


if __name__ == "__main__":
    main()
