import argparse
import csv
import json
import os
import shutil
import sys
import warnings
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
        description="Rotation-based elevation-angle ECDF for SNR/SINR."
    )
    parser.add_argument("--multi-beam-root", type=Path, default=snt_root / "Multi-Beam-LEO-Framework")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=INTEGRATION_ROOT / "results" / "lrfhss_communication" / "elevation_angle",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--n-user", type=int, default=100000)
    parser.add_argument("--rotation-trace-csv", type=Path, default=None)
    parser.add_argument("--rotation-step-metrics-csv", type=Path, default=None)
    return parser.parse_args()


def _prepare_runtime_framework_copy(src_root: Path, output_dir: Path) -> Path:
    del output_dir
    runtime_root = (INTEGRATION_ROOT / ".runtime" / "multi_beam").resolve()
    runtime_root.mkdir(parents=True, exist_ok=True)
    for item in src_root.iterdir():
        if not item.is_file():
            continue
        if item.suffix.lower() not in {".py", ".json"}:
            continue
        dst = runtime_root / item.name
        shutil.copy2(item, dst)
        if dst.suffix.lower() == ".json":
            try:
                os.chmod(dst, 0o666)
            except OSError:
                pass
    return runtime_root


def _load_rotation_step_scenarios(
    rotation_step_metrics_csv: Path | None,
    user_cap: int,
    max_steps_per_target: int = 2,
) -> dict[int, list[dict]]:
    targets = [90, 55, 25]
    out: dict[int, list[dict]] = {t: [] for t in targets}
    if rotation_step_metrics_csv is None or not rotation_step_metrics_csv.exists():
        return out

    candidates: dict[int, list[tuple[float, float, dict]]] = {t: [] for t in targets}
    with rotation_step_metrics_csv.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                step_idx = int(float(row.get("step", 0) or 0))
                elev = float(row.get("elevation_deg", "nan"))
                footprint_m = float(row.get("footprint_radius_m", 0.0) or 0.0)
                devices = max(0, int(float(row.get("estimated_devices_total", 0) or 0)))
                sat_lat_deg = float(row.get("satellite_latitude", "nan"))
                sat_lon_deg = float(row.get("satellite_longitude", "nan"))
            except ValueError:
                continue
            if (
                (not np.isfinite(elev))
                or (not np.isfinite(sat_lat_deg))
                or (not np.isfinite(sat_lon_deg))
                or footprint_m <= 0.0
                or devices <= 0
            ):
                continue
            n_user_step = max(1, min(int(user_cap), int(devices)))
            target = min(targets, key=lambda t: abs(float(elev) - float(t)))
            candidates[target].append(
                (
                    abs(float(elev) - float(target)),
                    -float(devices),
                    {
                        "step": int(step_idx),
                        "elevation_deg": float(elev),
                        "target_elevation_deg": int(target),
                        "footprint_m": float(footprint_m),
                        "footprint_km": int(round(float(footprint_m) / 1000.0)),
                        "n_user": int(n_user_step),
                        "devices": int(devices),
                        "satellite_latitude_deg": float(sat_lat_deg),
                        "satellite_longitude_deg": float(sat_lon_deg),
                    },
                )
            )

    for target in targets:
        ranked = sorted(candidates[target], key=lambda x: (x[0], x[1]))
        out[target] = [item[2] for item in ranked[: max(1, int(max_steps_per_target))]]
    return out


def _fallback_frames_by_elevation() -> dict[int, int]:
    return {90: 38537, 55: 33090, 25: 23932}


def _satellite_ecef_from_lat_lon(
    sat_lat_deg: float,
    sat_lon_deg: float,
    r_earth_m: float,
    h_satellite_m: float,
) -> np.ndarray:
    lat = np.radians(float(sat_lat_deg))
    lon = np.radians(float(sat_lon_deg))
    r = float(r_earth_m) + float(h_satellite_m)
    x = r * np.cos(lat) * np.cos(lon)
    y = r * np.cos(lat) * np.sin(lon)
    z = r * np.sin(lat)
    return np.array([x, y, z], dtype=float)


def _derive_footprints_from_rotation_sources(
    rotation_trace_csv: Path | None,
    rotation_step_metrics_csv: Path | None,
) -> list[int]:
    vals_km: set[int] = set()
    if rotation_trace_csv is not None and rotation_trace_csv.exists():
        with rotation_trace_csv.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                native_m = float(row.get("native_footprint_radius_m", 0.0) or 0.0)
                fallback_m = float(row.get("footprint_radius_m", 0.0) or 0.0)
                r_m = native_m if native_m > 0.0 else fallback_m
                if r_m > 0.0:
                    vals_km.add(int(round(r_m / 1000.0)))
    if not vals_km and rotation_step_metrics_csv is not None and rotation_step_metrics_csv.exists():
        with rotation_step_metrics_csv.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                r_m = float(row.get("footprint_radius_m", 0.0) or 0.0)
                if r_m > 0.0:
                    vals_km.add(int(round(r_m / 1000.0)))
    if not vals_km:
        return [200, 100, 50, 5]
    return sorted(vals_km, reverse=True)


def run_elevation_angle_study(
    multi_beam_root: Path,
    output_dir: Path,
    seed: int = 42,
    n_user: int = 100000,
    max_steps_per_target: int = 2,
    rotation_trace_csv: Path | None = None,
    rotation_step_metrics_csv: Path | None = None,
) -> dict:
    np.random.seed(int(seed))
    output_dir.mkdir(parents=True, exist_ok=True)
    runtime_root = _prepare_runtime_framework_copy(Path(multi_beam_root), output_dir)

    with _pushd(runtime_root):
        channel, network_geometry, params_mod, _, simulation = load_multi_beam_modules(runtime_root)
        params_mod.update_param_file(100e3)
        params_cfg = params_mod.read_params()
        ant_gain_db = float(params_cfg["antenna_gain_dB"])
        r_earth_m = float(params_cfg.get("r_earth", 6_371_000.0))
        h_satellite_m = float(params_cfg.get("h_satellite", 600_000.0))
        sat_pos = network_geometry.get_satellite_pos()
        sat_pos[:, 38537] = np.array([0.0, 0.0, 600e3], dtype=float)
        beam_centers = network_geometry.hex_grid_centers_two_rings()

        curves_by_target: dict[int, dict[str, list[np.ndarray]]] = {
            90: {"snr": [], "sinr": []},
            55: {"snr": [], "sinr": []},
            25: {"snr": [], "sinr": []},
        }
        metrics_rows: list[dict] = []
        elevation_list = [90, 55, 25]

        rotation_scenarios = _load_rotation_step_scenarios(
            rotation_step_metrics_csv=rotation_step_metrics_csv,
            user_cap=int(n_user),
            max_steps_per_target=max(1, int(max_steps_per_target)),
        )
        has_rotation_scenarios = any(len(v) > 0 for v in rotation_scenarios.values())

        if has_rotation_scenarios:
            mode = "rotation_step_based"
            all_scenarios: list[dict] = []
            for target in elevation_list:
                all_scenarios.extend(rotation_scenarios[target])
            scenario_iter = all_scenarios
            if tqdm is not None:
                scenario_iter = tqdm(all_scenarios, desc="RotationStepSNRSINR", unit="step")

            warnings.filterwarnings(
                "ignore",
                message=".*approximated method to compute the gaseous attenuation.*",
                category=RuntimeWarning,
            )
            for sc in scenario_iter:
                params_mod.update_param_file(float(sc["footprint_m"]))
                frame_idx = int(sc["step"])
                user_pos = network_geometry.get_user_position(int(sc["n_user"]))
                n_user_actual = int(user_pos.shape[1])

                i_sat_pos = _satellite_ecef_from_lat_lon(
                    sat_lat_deg=float(sc["satellite_latitude_deg"]),
                    sat_lon_deg=float(sc["satellite_longitude_deg"]),
                    r_earth_m=r_earth_m,
                    h_satellite_m=h_satellite_m,
                )
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
                target_elev = int(sc["target_elevation_deg"])
                curves_by_target[target_elev]["snr"].append(snr_db)
                curves_by_target[target_elev]["sinr"].append(sinr_db)

                metrics_rows.append(
                    {
                        "step": int(sc["step"]),
                        "elevation_deg": float(sc["elevation_deg"]),
                        "target_elevation_deg": int(target_elev),
                        "footprint_km": int(sc["footprint_km"]),
                        "n_user": int(n_user_actual),
                        "estimated_devices_total": int(sc["devices"]),
                        "snr_mean_db": float(np.mean(snr_db)),
                        "snr_p50_db": float(np.percentile(snr_db, 50)),
                        "snr_p90_db": float(np.percentile(snr_db, 90)),
                        "sinr_mean_db": float(np.mean(sinr_db)),
                        "sinr_p50_db": float(np.percentile(sinr_db, 50)),
                        "sinr_p90_db": float(np.percentile(sinr_db, 90)),
                        "snr_minus_sinr_mean_db": float(np.mean(snr_db - sinr_db)),
                    }
                )
        else:
            mode = "legacy_fallback"
            footprint_km = _derive_footprints_from_rotation_sources(
                rotation_trace_csv=rotation_trace_csv,
                rotation_step_metrics_csv=rotation_step_metrics_csv,
            )
            frames_by_elevation = _fallback_frames_by_elevation()
            fp_iter = zip(footprint_km, [km * 1e3 for km in footprint_km])
            if tqdm is not None and len(footprint_km) > 1:
                fp_iter = tqdm(list(fp_iter), desc="ServingAreas(rotation)", unit="fp")

            for f_km, f_m in fp_iter:
                params_mod.update_param_file(f_m)
                user_pos = network_geometry.get_user_position(int(n_user))
                n_user_actual = int(user_pos.shape[1])
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
                    curves_by_target[int(elev_deg)]["snr"].append(snr_db)
                    curves_by_target[int(elev_deg)]["sinr"].append(sinr_db)
                    metrics_rows.append(
                        {
                            "step": int(frame_idx),
                            "elevation_deg": float(elev_deg),
                            "target_elevation_deg": int(elev_deg),
                            "footprint_km": int(f_km),
                            "n_user": int(n_user_actual),
                            "estimated_devices_total": int(n_user_actual),
                            "snr_mean_db": float(np.mean(snr_db)),
                            "snr_p50_db": float(np.percentile(snr_db, 50)),
                            "snr_p90_db": float(np.percentile(snr_db, 90)),
                            "sinr_mean_db": float(np.mean(sinr_db)),
                            "sinr_p50_db": float(np.percentile(sinr_db, 50)),
                            "sinr_p90_db": float(np.percentile(sinr_db, 90)),
                            "snr_minus_sinr_mean_db": float(np.mean(snr_db - sinr_db)),
                        }
                    )

    angle_colors = {90: "#1f77b4", 55: "#ff7f0e", 25: "#2ca02c"}
    fig, axes = plt.subplots(1, 3, figsize=(16, 4.3), sharey=True)
    for ax, elev_deg in zip(axes, elevation_list):
        snr_chunks = curves_by_target[int(elev_deg)]["snr"]
        sinr_chunks = curves_by_target[int(elev_deg)]["sinr"]
        if not snr_chunks or not sinr_chunks:
            continue
        snr_all = np.concatenate(snr_chunks)
        sinr_all = np.concatenate(sinr_chunks)
        xs_snr, ys_snr = _ecdf_xy(snr_all)
        xs_sinr, ys_sinr = _ecdf_xy(sinr_all)
        ax.plot(xs_snr, ys_snr, color=angle_colors[elev_deg], linewidth=2.2, linestyle="-", label="SNR")
        ax.plot(xs_sinr, ys_sinr, color=angle_colors[elev_deg], linewidth=2.2, linestyle="--", label="SINR")
        ax.set_title(f"({chr(96 + elevation_list.index(elev_deg) + 1)}) {elev_deg} deg", fontsize=13, fontweight="bold")
        ax.set_xlabel("S(I)NR (dB)", fontsize=12)
        ax.grid(True, alpha=0.35)
        ax.set_ylim(0.0, 1.02)
        ax.legend(fontsize=8, loc="lower right", framealpha=0.9)
    axes[0].set_ylabel("ECDF", fontsize=12)
    fig.suptitle("Impact of rotation-step elevation on SNR/SINR ECDF", fontsize=15)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    plot_path = output_dir / "elevation_angle_ecdf_snr_sinr.png"
    fig.savefig(plot_path, dpi=220)
    plt.close(fig)

    agg_ecdf_rows: list[dict] = []
    fig_agg, axes_agg = plt.subplots(1, 2, figsize=(12.5, 4.6), sharey=True)
    for elev_deg in elevation_list:
        snr_chunks = curves_by_target[int(elev_deg)]["snr"]
        sinr_chunks = curves_by_target[int(elev_deg)]["sinr"]
        if not snr_chunks or not sinr_chunks:
            continue
        snr_all = np.concatenate(snr_chunks)
        sinr_all = np.concatenate(sinr_chunks)
        xs_snr, ys_snr = _ecdf_xy(snr_all)
        xs_sinr, ys_sinr = _ecdf_xy(sinr_all)
        axes_agg[0].plot(xs_snr, ys_snr, color=angle_colors[elev_deg], linewidth=2.2, label=f"{elev_deg} deg")
        axes_agg[1].plot(xs_sinr, ys_sinr, color=angle_colors[elev_deg], linewidth=2.2, label=f"{elev_deg} deg")
        for x, y in zip(xs_snr, ys_snr):
            agg_ecdf_rows.append(
                {"elevation_deg": int(elev_deg), "metric": "snr_db", "value_db": float(x), "ecdf": float(y)}
            )
        for x, y in zip(xs_sinr, ys_sinr):
            agg_ecdf_rows.append(
                {"elevation_deg": int(elev_deg), "metric": "sinr_db", "value_db": float(x), "ecdf": float(y)}
            )
    axes_agg[0].set_title("SNR ECDF by aggregate elevation angle", fontsize=12.5)
    axes_agg[1].set_title("SINR ECDF by aggregate elevation angle", fontsize=12.5)
    for ax in axes_agg:
        ax.set_xlabel("S(I)NR (dB)", fontsize=11)
        ax.grid(True, alpha=0.35)
        ax.set_ylim(0.0, 1.02)
        ax.legend(fontsize=9, loc="lower right", framealpha=0.9)
    axes_agg[0].set_ylabel("ECDF", fontsize=11)
    fig_agg.suptitle("S(I)NR vs ECDF for aggregate elevation angles", fontsize=14)
    fig_agg.tight_layout(rect=[0, 0, 1, 0.93])
    aggregate_plot_path = output_dir / "elevation_angle_ecdf_sinr_snr_aggregate_angles.png"
    fig_agg.savefig(aggregate_plot_path, dpi=220)
    plt.close(fig_agg)

    aggregate_ecdf_csv = output_dir / "elevation_angle_aggregate_ecdf.csv"
    with aggregate_ecdf_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["elevation_deg", "metric", "value_db", "ecdf"])
        writer.writeheader()
        writer.writerows(agg_ecdf_rows)

    metrics_csv = output_dir / "elevation_angle_metrics.csv"
    with metrics_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "step",
                "elevation_deg",
                "target_elevation_deg",
                "footprint_km",
                "n_user",
                "estimated_devices_total",
                "snr_mean_db",
                "snr_p50_db",
                "snr_p90_db",
                "sinr_mean_db",
                "sinr_p50_db",
                "sinr_p90_db",
                "snr_minus_sinr_mean_db",
            ],
        )
        writer.writeheader()
        writer.writerows(metrics_rows)

    summary = {
        "multi_beam_root": str(multi_beam_root.resolve()),
        "runtime_multi_beam_root": str(runtime_root.resolve()),
        "output_dir": str(output_dir.resolve()),
        "seed": int(seed),
        "n_user_cap": int(n_user),
        "max_steps_per_target": int(max(1, int(max_steps_per_target))),
        "mode": mode,
        "elevation_deg": [90, 55, 25],
        "footprint_km": sorted({int(r["footprint_km"]) for r in metrics_rows}, reverse=True),
        "plot": str(plot_path.resolve()),
        "metrics_csv": str(metrics_csv.resolve()),
        "aggregate_ecdf_plot": str(aggregate_plot_path.resolve()),
        "aggregate_ecdf_csv": str(aggregate_ecdf_csv.resolve()),
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
        max_steps_per_target=2,
        rotation_trace_csv=args.rotation_trace_csv,
        rotation_step_metrics_csv=args.rotation_step_metrics_csv,
    )
    print("Elevation-angle study completed.")
    print(f"Plot:        {summary['plot']}")
    print(f"Metrics CSV: {summary['metrics_csv']}")


if __name__ == "__main__":
    main()
