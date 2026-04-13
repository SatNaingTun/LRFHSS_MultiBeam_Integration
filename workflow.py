import csv
import json
from pathlib import Path
import random

import numpy as np

from coverage_population import export_coverage_population_csv
from demodulator_power import DemodulatorPowerModel
from multi_beam_connector import load_multi_beam_modules
from workflow_tasks.lrfhss_communication import build_comparison_series, list_available_demod_counts
from workflow_tasks.lrfhss_flowtask import (
    _build_node_loads,
    _check_nodes_and_demods_for_coverage,
    _extract_series_value_for_nodes,
    _load_trace_steps,
    _normalize_demods,
    _sanitize_filename,
    _select_available_demod,
    _stable_country_hash,
    plot_country_sent_vs_payload,
)
from workflow_tasks.orbit_visibility import compute_orbit_parameters, compute_satellite_orbit
from workflow_tasks.elevation_angle import run_elevation_angle_study

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    plt = None

try:
    from tqdm import tqdm
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    tqdm = None

__all__ = ["run_workflow"]


def _ecdf_xy(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    x = np.sort(values.astype(float))
    n = x.size
    if n <= 0:
        return np.array([], dtype=float), np.array([], dtype=float)
    y = np.arange(1, n + 1, dtype=float) / float(n)
    return x, y


def _plot_collision_rate_ecdf(collision_rates: np.ndarray, out_png: Path, scope_label: str = "active_steps") -> None:
    if plt is None:
        raise ModuleNotFoundError("matplotlib is required for plotting. Install with: pip install matplotlib")
    xs, ys = _ecdf_xy(collision_rates)
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(xs, ys, color="#1f77b4", linewidth=2.0)
    title_suffix = "active steps" if scope_label == "active_steps" else "all steps"
    ax.set_title(f"Collision Rate ECDF ({title_suffix})", fontsize=13)
    ax.set_xlabel("Collision rate (1 - decoded payloads / sent packets)", fontsize=11)
    ax.set_ylabel("ECDF", fontsize=11)
    ax.grid(True, linestyle="-", linewidth=0.5, alpha=0.35)
    ax.set_ylim(0.0, 1.02)
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=220)
    plt.close(fig)


def _plot_collision_rate_and_power(
    steps: np.ndarray,
    collision_rate: np.ndarray,
    total_power_w: np.ndarray,
    out_png: Path,
) -> None:
    if plt is None:
        raise ModuleNotFoundError("matplotlib is required for plotting. Install with: pip install matplotlib")
    fig, ax1 = plt.subplots(figsize=(10, 5))
    ax2 = ax1.twinx()

    ax1.plot(steps, collision_rate, color="#1f77b4", linewidth=2, label="Collision rate")
    ax2.plot(steps, total_power_w, color="#d62728", linewidth=2, label="Total power (W)")
    ax1.set_xlabel("Step", fontsize=11)
    ax1.set_ylabel("Collision rate", color="#1f77b4", fontsize=11)
    ax2.set_ylabel("Power (W)", color="#d62728", fontsize=11)
    ax1.grid(True, linestyle="-", linewidth=0.5, alpha=0.35)
    ax1.set_ylim(0.0, max(1.02, float(np.nanmax(collision_rate)) * 1.05 if collision_rate.size else 1.02))
    fig.suptitle("Per-step collision rate and satellite power", fontsize=13)

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="best")
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=220)
    plt.close(fig)


def _plot_stepwise_sent_vs_decoded(records: list[dict], out_png: Path) -> None:
    if not records:
        return
    shaped_records = [
        {
            "selected_nodes": float(r.get("sent_packets_used", 0.0) or 0.0),
            "decoded_payload_mean": float(r.get("decoded_payload_mean", 0.0) or 0.0),
        }
        for r in records
    ]
    plot_country_sent_vs_payload(
        records=shaped_records,
        out_png=out_png,
        title="Stepwise sent packets vs decoded payload (all covered countries)",
    )


def _sampled_indices(total_count: int, max_points: int = 2000) -> np.ndarray:
    n = int(max(0, total_count))
    if n <= 0:
        return np.array([], dtype=int)
    stride = int(max(1, np.ceil(n / max(1, int(max_points)))))
    return np.arange(0, n, stride, dtype=int)


def _plot_collision_rate_ecdf_by_elevation(
    step_records: list[dict],
    out_png: Path,
    out_csv: Path,
) -> None:
    if plt is None:
        raise ModuleNotFoundError("matplotlib is required for plotting. Install with: pip install matplotlib")

    bins = [
        ("<=25deg", -1e9, 25.0, "#1f77b4"),
        ("25deg-55deg", 25.0, 55.0, "#ff7f0e"),
        (">55deg", 55.0, 1e9, "#2ca02c"),
    ]

    fig, ax = plt.subplots(figsize=(8.5, 5.5))
    ecdf_rows: list[dict] = []
    plotted = 0
    for label, lo, hi, color in bins:
        vals = []
        for row in step_records:
            elev = float(row.get("elevation_deg", np.nan))
            sent = int(row.get("sent_packets_sum", 0) or 0)
            if sent <= 0 or not np.isfinite(elev):
                continue
            if lo < elev <= hi:
                vals.append(float(row.get("collision_rate", 0.0) or 0.0))

        arr = np.array(vals, dtype=float)
        if arr.size <= 0:
            continue
        xs, ys = _ecdf_xy(arr)
        ax.plot(xs, ys, linewidth=2.0, label=f"{label} (n={arr.size})", color=color)
        plotted += 1
        for x, y in zip(xs, ys):
            ecdf_rows.append({"elevation_bin": label, "collision_rate": float(x), "ecdf": float(y)})

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["elevation_bin", "collision_rate", "ecdf"])
        w.writeheader()
        w.writerows(ecdf_rows)

    if plotted <= 0:
        plt.close(fig)
        return

    ax.set_title("Collision Rate ECDF by Elevation Angle", fontsize=13)
    ax.set_xlabel("Collision rate (1 - decoded payloads / sent packets)", fontsize=11)
    ax.set_ylabel("ECDF", fontsize=11)
    ax.grid(True, linestyle="-", linewidth=0.5, alpha=0.35)
    ax.set_ylim(0.0, 1.02)
    ax.legend(loc="lower right", fontsize=9)
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=220)
    plt.close(fig)


def _plot_nodes_vs_decoded_with_demods(
    records: list[dict],
    out_png: Path,
    out_csv: Path,
) -> None:
    if plt is None:
        raise ModuleNotFoundError("matplotlib is required for plotting. Install with: pip install matplotlib")
    if not records:
        return

    grouped: dict[int, dict[str, list[float]]] = {}
    for row in records:
        n = int(float(row.get("sent_packets_used", 0) or 0))
        if n <= 0:
            continue
        grouped.setdefault(n, {"decoded": [], "idle": [], "busy": []})
        grouped[n]["decoded"].append(float(row.get("decoded_payload_mean", 0.0) or 0.0))
        grouped[n]["idle"].append(float(row.get("idle_demodulators", 0.0) or 0.0))
        grouped[n]["busy"].append(float(row.get("busy_demodulators", 0.0) or 0.0))

    if not grouped:
        return

    xs = np.array(sorted(grouped.keys()), dtype=float)
    decoded = np.array([float(np.mean(grouped[int(x)]["decoded"])) for x in xs], dtype=float)
    idle = np.array([float(np.mean(grouped[int(x)]["idle"])) for x in xs], dtype=float)
    busy = np.array([float(np.mean(grouped[int(x)]["busy"])) for x in xs], dtype=float)

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "sent_packets_used",
                "decoded_payload_mean",
                "idle_demodulators_mean",
                "busy_demodulators_mean",
            ],
        )
        w.writeheader()
        for x, d, i, b in zip(xs, decoded, idle, busy):
            w.writerow(
                {
                    "sent_packets_used": int(x),
                    "decoded_payload_mean": float(d),
                    "idle_demodulators_mean": float(i),
                    "busy_demodulators_mean": float(b),
                }
            )

    fig, ax1 = plt.subplots(figsize=(10, 5.5))
    ax2 = ax1.twinx()
    ax1.plot(xs, decoded, color="#1f77b4", linewidth=2, marker="o", label="Decoded payload")
    ax1.plot(xs, xs, color="black", linewidth=1.6, linestyle="--", label="x=y")
    ax2.plot(xs, idle, color="#ff7f0e", linewidth=2, label="Idle demod")
    ax2.plot(xs, busy, color="#2ca02c", linewidth=2, label="Busy demod")
    ax1.set_xscale("log")
    ax1.set_xlabel("Sent packets (nodes)", fontsize=11)
    ax1.set_ylabel("Decoded payload", fontsize=11, color="#1f77b4")
    ax2.set_ylabel("Demodulator count", fontsize=11)
    ax1.grid(True, which="both", linestyle="-", linewidth=0.5, alpha=0.35)
    ax1.set_title("Nodes vs Decoded Payload with Idle/Busy Demodulators", fontsize=13)

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="best")
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=220)
    plt.close(fig)


def _aggregate_elevation_metrics(metrics_csv: Path, out_csv: Path) -> str | None:
    if not metrics_csv.exists():
        return None
    grouped: dict[int, dict[str, list[float]]] = {}
    with metrics_csv.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            elev = int(float(row.get("elevation_deg", 0) or 0))
            grouped.setdefault(
                elev,
                {
                    "snr_mean_db": [],
                    "snr_p50_db": [],
                    "snr_p90_db": [],
                    "sinr_mean_db": [],
                    "sinr_p50_db": [],
                    "sinr_p90_db": [],
                },
            )
            for k in grouped[elev]:
                grouped[elev][k].append(float(row.get(k, 0.0) or 0.0))

    if not grouped:
        return None

    out_rows: list[dict] = []
    for elev in sorted(grouped.keys()):
        vals = grouped[elev]
        out_rows.append(
            {
                "elevation_deg": int(elev),
                "footprint_count": int(len(vals["snr_mean_db"])),
                "snr_mean_db": float(np.mean(np.array(vals["snr_mean_db"], dtype=float))),
                "snr_p50_db": float(np.mean(np.array(vals["snr_p50_db"], dtype=float))),
                "snr_p90_db": float(np.mean(np.array(vals["snr_p90_db"], dtype=float))),
                "sinr_mean_db": float(np.mean(np.array(vals["sinr_mean_db"], dtype=float))),
                "sinr_p50_db": float(np.mean(np.array(vals["sinr_p50_db"], dtype=float))),
                "sinr_p90_db": float(np.mean(np.array(vals["sinr_p90_db"], dtype=float))),
            }
        )

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "elevation_deg",
                "footprint_count",
                "snr_mean_db",
                "snr_p50_db",
                "snr_p90_db",
                "sinr_mean_db",
                "sinr_p50_db",
                "sinr_p90_db",
            ],
        )
        w.writeheader()
        w.writerows(out_rows)
    return str(out_csv.resolve())


def _normalize_elevation_deg(values: np.ndarray) -> np.ndarray:
    # Convert wrapped angular output to physical elevation in [0, 90] deg.
    wrapped = ((values + 180.0) % 360.0) - 180.0
    return np.clip(np.abs(wrapped), 0.0, 90.0)


def _load_step_country_coverage(step_country_csv: Path) -> dict[int, list[dict]]:
    by_step: dict[int, list[dict]] = {}
    with step_country_csv.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            step = int(float(row.get("step", 0) or 0))
            by_step.setdefault(step, []).append(
                {
                    "country": str(row.get("country", "")).strip(),
                    "iso3": str(row.get("iso3", "")).strip() or "UNK",
                    "population_coverage_share": float(row.get("population_coverage_share", 0.0) or 0.0),
                    "step_devices_total": max(0, int(float(row.get("step_devices_total", 0) or 0))),
                    "step_demodulators_total": max(0, int(float(row.get("step_demodulators_total", 0) or 0))),
                    "overlap_fraction": float(row.get("overlap_fraction", 0.0) or 0.0),
                }
            )
    return by_step


def run_workflow(
    multi_beam_root: Path,
    lrfhss_root: Path,
    output_dir: Path,
    seed: int,
    node_min: int,
    node_max: int,
    node_points: int,
    demodulator_options: list[int],
    nodes_list: list[int] | None,
    reference_csv: Path,
    scenario_steps: int = 120,
    step_seconds: float = 228.0,
    runs_per_point: int = 10,
    baseline_circuit_power_w: float = 35.0,
    per_idle_demodulator_power_w: float = 0.12,
    per_busy_demodulator_power_w: float = 0.80,
    demod_tx_capacity_per_step: float = 250.0,
    elevation_user_cap: int = 5000,
    elevation_steps_per_angle: int = 1,
) -> None:
    del lrfhss_root, runs_per_point
    node_loads = _build_node_loads(node_min=node_min, node_max=node_max, node_points=node_points, nodes_list=nodes_list)
    demods = _normalize_demods(demodulator_options)
    available_reference_demods = list_available_demod_counts(reference_csv=reference_csv, coding_rate=1, family="driver")
    if not available_reference_demods:
        raise ValueError(f"No available demod rows found in reference CSV: {reference_csv}")

    _, network_geometry, params_mod, utils_mod, _ = load_multi_beam_modules(multi_beam_root)
    sat_pos, orbit_task_info = compute_satellite_orbit(
        network_geometry=network_geometry,
        params_mod=params_mod,
        step_seconds=float(step_seconds),
        scenario_steps=max(1, int(scenario_steps)),
    )
    orbit_cfg = orbit_task_info["orbit_task"]["orbit_config"]
    orbit_parameters = compute_orbit_parameters(sat_pos=sat_pos, step_seconds=float(orbit_cfg["time_step_s"]))
    orbit_period_s = float(
        2.0
        * np.pi
        * np.sqrt(
            (float(orbit_cfg["earth_radius_m"] + orbit_cfg["altitude_m"]) ** 3) / float(orbit_cfg["earth_mu_m3_s2"])
        )
    )
    one_orbit_frames = int(np.ceil(orbit_period_s / max(float(orbit_cfg["time_step_s"]), 1e-12))) + 1

    params_config = params_mod.read_params() if params_mod is not None and hasattr(params_mod, "read_params") else {}
    coverage_csv_path = output_dir / "csv" / "coverage_population_devices.csv"
    coverage_trace_csv_path = output_dir / "csv" / "coverage_track_trace.csv"
    coverage_step_country_csv_path = output_dir / "csv" / "coverage_step_country_shares.csv"
    coverage_input_csv = Path("Data") / "adult_population_country_coordinates.csv"
    lat_raw = orbit_task_info.get("satellite_ground_track_lat_deg")
    lon_raw = orbit_task_info.get("satellite_ground_track_lon_deg")
    if lat_raw is None or lon_raw is None:
        raise ValueError("Orbit rotation did not provide ground-track arrays.")
    lat = np.array(lat_raw, dtype=float, copy=True)
    lon = np.array(lon_raw, dtype=float, copy=True)
    one_orbit_track_len = int(min(one_orbit_frames, min(lat.size, lon.size)))

    sampled_frame_idx = _sampled_indices(one_orbit_track_len, max_points=2000)
    device_penetration_ratio = 0.001
    devices_per_demodulator = 250
    coverage_info = export_coverage_population_csv(
        input_csv=coverage_input_csv,
        output_csv=coverage_csv_path,
        params_config=params_config,
        ground_track_lat_deg=lat[:one_orbit_track_len],
        ground_track_lon_deg=lon[:one_orbit_track_len],
        max_ground_track_points=2000,
        trace_csv=coverage_trace_csv_path,
        step_country_csv=coverage_step_country_csv_path,
        print_track_changes=True,
        device_penetration_ratio=device_penetration_ratio,
        devices_per_demodulator=devices_per_demodulator,
    )

    node_demod_check = _check_nodes_and_demods_for_coverage(
        node_loads=node_loads,
        demodulator_options=demods,
        coverage_info=coverage_info,
    )
    filtered_nodes = node_demod_check["node_count_options_in_coverage"]
    filtered_demods = node_demod_check["demod_count_options_in_coverage"]
    if not filtered_nodes or not filtered_demods:
        raise ValueError("No node/demod options remain after coverage filtering.")

    trace_steps = _load_trace_steps(trace_csv_path=coverage_trace_csv_path)
    step_country_coverage = _load_step_country_coverage(step_country_csv=coverage_step_country_csv_path)
    if not trace_steps:
        raise ValueError("No coverage trace steps found for one-orbit simulation.")
    step_count = len(trace_steps)
    sampled_frame_idx = sampled_frame_idx[:step_count]
    step_elevation_deg = np.full(step_count, np.nan, dtype=float)
    if utils_mod is not None and sampled_frame_idx.size > 0:
        try:
            elev_all_deg = (
                utils_mod.get_elevation_angle_from_center(sat_pos[0, :], sat_pos[2, :]) * 180.0 / np.pi
            )
            elev_all_deg = _normalize_elevation_deg(np.array(elev_all_deg, dtype=float))
            step_elevation_deg = np.array(elev_all_deg[sampled_frame_idx], dtype=float)
        except Exception:
            step_elevation_deg = np.full(step_count, np.nan, dtype=float)

    country_csv_dir = output_dir / "country_csv"
    country_csv_dir.mkdir(parents=True, exist_ok=True)
    aggregate_csv = output_dir / "covered_countries_lrfhss_stepwise_results.csv"
    step_fieldnames = [
        "country",
        "iso3",
        "step",
        "satellite_latitude",
        "satellite_longitude",
        "country_share",
        "step_devices_total",
        "step_demods_total",
        "selected_nodes",
        "selected_demods",
        "series_demod_used",
        "sent_packets_used",
        "decoded_payload_base",
        "decoded_payload_mean",
        "collision_rate",
        "elevation_deg",
        "footprint_radius_m",
        "footprint_area_km2",
        "idle_demodulators",
        "busy_demodulators",
    ]
    all_records: list[dict] = []
    country_records_map: dict[tuple[str, str], list[dict]] = {}
    generated_country_csv: list[str] = []
    combined_plot_file: str | None = None
    stepwise_sent_vs_payload_plot_file: str | None = None
    collision_ecdf_plot_file: str | None = None
    collision_ecdf_by_elevation_plot_file: str | None = None
    collision_rate_power_plot_file: str | None = None
    step_metrics_csv_path: str | None = None
    collision_rate_ecdf_csv_path: str | None = None
    collision_rate_ecdf_by_elevation_csv_path: str | None = None
    nodes_decoded_demod_csv_path: str | None = None
    nodes_decoded_demod_plot_file: str | None = None
    elevation_summary: dict | None = None

    series_cache: dict[int, any] = {}
    step_metric_records: list[dict] = []
    demod_power_model = DemodulatorPowerModel(
        idle_power_w=float(per_idle_demodulator_power_w),
        busy_power_w=float(per_busy_demodulator_power_w),
    )

    with aggregate_csv.open("w", encoding="utf-8", newline="") as f_step:
        writer = csv.DictWriter(f_step, fieldnames=step_fieldnames)
        writer.writeheader()

        step_iter = tqdm(trace_steps, desc="Rotation steps", unit="step") if tqdm is not None else trace_steps
        for step_row in step_iter:
            step_idx = int(step_row["step"])
            elevation_deg = float(step_elevation_deg[step_idx]) if 0 <= step_idx < step_elevation_deg.size else float("nan")
            step_sat_lat = float(step_row["satellite_latitude"])
            step_sat_lon = float(step_row["satellite_longitude"])
            step_countries = step_country_coverage.get(step_idx, [])
            step_devices_total = max(0, int(step_row.get("estimated_devices_total", 0) or 0))
            step_demods_total = max(0, int(step_row.get("estimated_demodulators_total", 0) or 0))
            step_footprint_radius_m = float(step_row.get("footprint_radius_m", 0.0) or 0.0)
            step_footprint_area_km2 = float(step_row.get("footprint_area_km2", 0.0) or 0.0)
            countries_used_in_step = 0
            step_sent_packets_sum = 0
            step_decoded_payload_sum = 0.0

            country_iter = (
                tqdm(step_countries, desc=f"Countries@step{step_idx}", unit="country", leave=False)
                if tqdm is not None
                else step_countries
            )
            for country in country_iter:
                country_name = country["country"]
                iso3 = country["iso3"] or "UNK"
                share = float(country["population_coverage_share"])

                country_devices_step = max(0, int(round(step_devices_total * share)))
                country_demods_step = max(0, int(round(step_demods_total * share)))
                valid_nodes = [n for n in filtered_nodes if n <= country_devices_step]
                valid_demods = [d for d in filtered_demods if d <= country_demods_step]
                if not valid_nodes or not valid_demods:
                    continue

                country_seed = _stable_country_hash(country_name, iso3)
                step_seed = int(seed) + int(step_idx) * 1_000_003 + int(country_seed)
                rng = random.Random(step_seed)

                selected_nodes = int(rng.choice(sorted(valid_nodes)))
                selected_demods = int(rng.choice(sorted(valid_demods)))
                series_demod = _select_available_demod(selected_demods, available_reference_demods)
                if series_demod is None:
                    continue

                if series_demod not in series_cache:
                    series_cache[series_demod] = build_comparison_series(
                        reference_csv=reference_csv,
                        demods=series_demod,
                        coding_rate=1,
                        metric="dec_payld",
                        drop_mode="rlydd",
                        include_lifan=False,
                        include_infp=False,
                        node_min=None,
                        node_max=None,
                        selected_nodes=None,
                    )
                series = series_cache[series_demod]
                sent_packets_used, decoded_base, decoded_earlydd = _extract_series_value_for_nodes(
                    series=series,
                    target_nodes=selected_nodes,
                )

                if sent_packets_used > 0:
                    collection_rate = float(decoded_earlydd / float(sent_packets_used))
                    collision_rate = float(max(0.0, 1.0 - collection_rate))
                else:
                    collision_rate = 0.0
                demod_eval_country = demod_power_model.evaluate(
                    visible=True,
                    allocated_demods=max(0, int(selected_demods)),
                    tx_count=max(0, int(sent_packets_used)),
                    demod_tx_capacity_per_step=float(max(1e-9, demod_tx_capacity_per_step)),
                )
                row = {
                    "country": country_name,
                    "iso3": iso3,
                    "step": step_idx,
                    "satellite_latitude": step_sat_lat,
                    "satellite_longitude": step_sat_lon,
                    "country_share": float(share),
                    "step_devices_total": int(step_devices_total),
                    "step_demods_total": int(step_demods_total),
                    "selected_nodes": int(selected_nodes),
                    "selected_demods": int(selected_demods),
                    "series_demod_used": int(series_demod),
                    "sent_packets_used": int(sent_packets_used),
                    "decoded_payload_base": float(decoded_base),
                    "decoded_payload_mean": float(decoded_earlydd),
                    "collision_rate": collision_rate,
                    "elevation_deg": float(elevation_deg),
                    "footprint_radius_m": float(step_footprint_radius_m),
                    "footprint_area_km2": float(step_footprint_area_km2),
                    "idle_demodulators": int(demod_eval_country.idle_demods),
                    "busy_demodulators": int(demod_eval_country.busy_demods),
                }
                writer.writerow(row)
                all_records.append(row)
                country_records_map.setdefault((country_name, iso3), []).append(row)
                countries_used_in_step += 1
                step_sent_packets_sum += int(sent_packets_used)
                step_decoded_payload_sum += float(decoded_earlydd)

            demod_eval = demod_power_model.evaluate(
                visible=True,
                allocated_demods=max(0, int(step_demods_total)),
                tx_count=max(0, int(step_sent_packets_sum)),
                demod_tx_capacity_per_step=float(max(1e-9, demod_tx_capacity_per_step)),
            )
            total_power_w = float(baseline_circuit_power_w + demod_eval.total_demod_power_w)
            formula_check_w = float(
                baseline_circuit_power_w
                + demod_eval.idle_demods * per_idle_demodulator_power_w
                + demod_eval.busy_demods * per_busy_demodulator_power_w
            )
            step_metric_records.append(
                {
                    "step": int(step_idx),
                    "satellite_latitude": step_sat_lat,
                    "satellite_longitude": step_sat_lon,
                    "elevation_deg": float(elevation_deg),
                    "footprint_radius_m": float(step_footprint_radius_m),
                    "footprint_area_km2": float(step_footprint_area_km2),
                    "countries_used": int(countries_used_in_step),
                    "estimated_devices_total": int(step_devices_total),
                    "estimated_demodulators_total": int(step_demods_total),
                    "sent_packets_sum": int(step_sent_packets_sum),
                    "decoded_payload_sum": float(step_decoded_payload_sum),
                    "collision_rate": float(
                        max(0.0, 1.0 - (step_decoded_payload_sum / float(step_sent_packets_sum)))
                        if step_sent_packets_sum > 0
                        else 0.0
                    ),
                    "busy_demodulators": int(demod_eval.busy_demods),
                    "idle_demodulators": int(demod_eval.idle_demods),
                    "demod_utilization": float(demod_eval.utilization),
                    "baseline_circuit_power_w": float(baseline_circuit_power_w),
                    "per_idle_demodulator_power_w": float(per_idle_demodulator_power_w),
                    "per_busy_demodulator_power_w": float(per_busy_demodulator_power_w),
                    "total_power_w": float(total_power_w),
                    "power_formula_check_w": float(formula_check_w),
                }
            )

    for (country_name, iso3), rows in sorted(country_records_map.items()):
        if not rows:
            continue
        safe = _sanitize_filename(f"{iso3}_{country_name}")
        country_csv = country_csv_dir / f"{safe}_lrfhss_stepwise.csv"
        with country_csv.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        generated_country_csv.append(str(country_csv.resolve()))

    country_avg_csv = output_dir / "covered_countries_lrfhss_country_avg.csv"
    if all_records:
        grouped: dict[tuple[str, str], dict[str, list[float]]] = {}
        for row in all_records:
            key = (str(row["country"]), str(row["iso3"]))
            grouped.setdefault(key, {"sent_packets_used": [], "decoded_payload_mean": [], "collision_rate": []})
            grouped[key]["sent_packets_used"].append(float(row["sent_packets_used"]))
            grouped[key]["decoded_payload_mean"].append(float(row["decoded_payload_mean"]))
            grouped[key]["collision_rate"].append(float(row["collision_rate"]))

        country_avg_records: list[dict] = []
        for (country_name, iso3), vals in sorted(grouped.items()):
            country_avg_records.append(
                {
                    "country": country_name,
                    "iso3": iso3,
                    "selected_nodes": float(np.mean(np.array(vals["sent_packets_used"], dtype=float))),
                    "decoded_payload_mean": float(np.mean(np.array(vals["decoded_payload_mean"], dtype=float))),
                    "collision_rate_mean": float(np.mean(np.array(vals["collision_rate"], dtype=float))),
                    "step_samples": int(len(vals["decoded_payload_mean"])),
                }
            )

        with country_avg_csv.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(country_avg_records[0].keys()))
            w.writeheader()
            w.writerows(country_avg_records)
        country_avg_csv_path = str(country_avg_csv.resolve())

        combined_plot = output_dir / "sent_packets_vs_decoded_payload_country_avg.png"
        try:
            plot_country_sent_vs_payload(
                records=country_avg_records,
                out_png=combined_plot,
                title="Country-average decoded payloads across one rotation",
            )
            combined_plot_file = str(combined_plot.resolve())
        except ModuleNotFoundError as exc:
            print(f"[plot skipped] {exc}")

        stepwise_plot = output_dir / "sent_packets_vs_decoded_payload_stepwise_aggregate.png"
        try:
            _plot_stepwise_sent_vs_decoded(all_records, stepwise_plot)
            stepwise_sent_vs_payload_plot_file = str(stepwise_plot.resolve())
        except ModuleNotFoundError as exc:
            print(f"[plot skipped] {exc}")
        aggregate_csv_path = str(aggregate_csv.resolve())
    else:
        aggregate_csv_path = None
        country_avg_csv_path = None

    if step_metric_records:
        step_metrics_csv = output_dir / "csv" / "collision_rate_step_metrics.csv"
        step_metrics_csv.parent.mkdir(parents=True, exist_ok=True)
        with step_metrics_csv.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(step_metric_records[0].keys()))
            writer.writeheader()
            writer.writerows(step_metric_records)
        step_metrics_csv_path = str(step_metrics_csv.resolve())

        step_collision_rate = np.array([float(r["collision_rate"]) for r in step_metric_records], dtype=float)
        step_sent_packets = np.array([int(r["sent_packets_sum"]) for r in step_metric_records], dtype=int)
        active_mask = step_sent_packets > 0
        ecdf_source_label = "active_steps" if np.any(active_mask) else "all_steps"
        ecdf_collision_rate = step_collision_rate[active_mask] if np.any(active_mask) else step_collision_rate
        ecdf_x, ecdf_y = _ecdf_xy(ecdf_collision_rate)
        ecdf_csv = output_dir / "csv" / "collision_rate_ecdf.csv"
        with ecdf_csv.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["scope", "collision_rate", "ecdf"])
            writer.writeheader()
            for x, y in zip(ecdf_x, ecdf_y):
                writer.writerow({"scope": ecdf_source_label, "collision_rate": float(x), "ecdf": float(y)})
        collision_rate_ecdf_csv_path = str(ecdf_csv.resolve())

        ecdf_plot = output_dir / "plots" / "collision_rate_ecdf.png"
        try:
            _plot_collision_rate_ecdf(ecdf_collision_rate, ecdf_plot, scope_label=ecdf_source_label)
            collision_ecdf_plot_file = str(ecdf_plot.resolve())
        except ModuleNotFoundError as exc:
            print(f"[plot skipped] {exc}")

        ecdf_by_elev_plot = output_dir / "plots" / "collision_rate_ecdf_by_elevation.png"
        ecdf_by_elev_csv = output_dir / "csv" / "collision_rate_ecdf_by_elevation.csv"
        try:
            _plot_collision_rate_ecdf_by_elevation(
                step_records=step_metric_records,
                out_png=ecdf_by_elev_plot,
                out_csv=ecdf_by_elev_csv,
            )
            collision_ecdf_by_elevation_plot_file = str(ecdf_by_elev_plot.resolve())
            collision_rate_ecdf_by_elevation_csv_path = str(ecdf_by_elev_csv.resolve())
        except ModuleNotFoundError as exc:
            print(f"[plot skipped] {exc}")

        step_series_plot = output_dir / "plots" / "collision_rate_vs_power_timeseries.png"
        step_values = np.array([float(r["step"]) for r in step_metric_records], dtype=float)
        power_values = np.array([float(r["total_power_w"]) for r in step_metric_records], dtype=float)
        try:
            _plot_collision_rate_and_power(
                steps=step_values,
                collision_rate=step_collision_rate,
                total_power_w=power_values,
                out_png=step_series_plot,
            )
            collision_rate_power_plot_file = str(step_series_plot.resolve())
        except ModuleNotFoundError as exc:
            print(f"[plot skipped] {exc}")

    if all_records:
        nodes_demod_csv = output_dir / "csv" / "nodes_vs_decoded_payload_demod_states.csv"
        nodes_demod_plot = output_dir / "plots" / "nodes_vs_decoded_payload_demod_states.png"
        try:
            _plot_nodes_vs_decoded_with_demods(
                records=all_records,
                out_png=nodes_demod_plot,
                out_csv=nodes_demod_csv,
            )
            nodes_decoded_demod_csv_path = str(nodes_demod_csv.resolve())
            nodes_decoded_demod_plot_file = str(nodes_demod_plot.resolve())
        except ModuleNotFoundError as exc:
            print(f"[plot skipped] {exc}")

    try:
        elevation_output_dir = output_dir / "elevation_angle"
        elevation_summary = run_elevation_angle_study(
            multi_beam_root=multi_beam_root,
            output_dir=elevation_output_dir,
            seed=int(seed),
            n_user=max(1, int(elevation_user_cap)),
            max_steps_per_target=max(1, int(elevation_steps_per_angle)),
            rotation_trace_csv=coverage_trace_csv_path,
            rotation_step_metrics_csv=(
                Path(step_metrics_csv_path) if step_metrics_csv_path is not None else None
            ),
        )
    except (ModuleNotFoundError, PermissionError, OSError) as exc:
        print(f"[elevation plot skipped] {exc}")

    elevation_plot_file = None
    elevation_metrics_file = None
    elevation_aggregate_csv = None
    elevation_aggregate_ecdf_plot_file = None
    elevation_aggregate_ecdf_csv = None
    elevation_output_dir = output_dir / "elevation_angle"
    fallback_plot = elevation_output_dir / "elevation_angle_ecdf_snr_sinr.png"
    fallback_metrics = elevation_output_dir / "elevation_angle_metrics.csv"
    fallback_aggregate_plot = elevation_output_dir / "elevation_angle_ecdf_sinr_snr_aggregate_angles.png"
    fallback_aggregate_ecdf_csv = elevation_output_dir / "elevation_angle_aggregate_ecdf.csv"
    if elevation_summary:
        elevation_plot_file = elevation_summary.get("plot")
        elevation_metrics_file = elevation_summary.get("metrics_csv")
        elevation_aggregate_ecdf_plot_file = elevation_summary.get("aggregate_ecdf_plot")
        elevation_aggregate_ecdf_csv = elevation_summary.get("aggregate_ecdf_csv")
    else:
        if fallback_plot.exists():
            elevation_plot_file = str(fallback_plot.resolve())
        if fallback_metrics.exists():
            elevation_metrics_file = str(fallback_metrics.resolve())
        if fallback_aggregate_plot.exists():
            elevation_aggregate_ecdf_plot_file = str(fallback_aggregate_plot.resolve())
        if fallback_aggregate_ecdf_csv.exists():
            elevation_aggregate_ecdf_csv = str(fallback_aggregate_ecdf_csv.resolve())

    if elevation_metrics_file is not None:
        elevation_aggregate_csv = _aggregate_elevation_metrics(
            metrics_csv=Path(elevation_metrics_file),
            out_csv=(output_dir / "elevation_angle" / "elevation_angle_aggregate.csv"),
        )

    summary = {
        "workflow": [
            "Propagate LEO orbit using two-body Kepler equations",
            "At each rotation step derive coverage-driven devices/demods from GPW proportion",
            "Use reference-series curves to estimate decoded payload and collision rate",
            "Compute power per step using baseline + idle/busy demodulator formula",
            "Export CSV results and ECDF/stepwise plots",
            "END",
        ],
        "mode": "rotation_stepwise_reference_series_lrfhss",
        "orbit_task": orbit_task_info["orbit_task"],
        "citations": {
            "orbit_model": orbit_task_info["orbit_task"].get("citations", []),
            "reference_replication_source": str(Path("replicate_paper.py").resolve()),
        },
        "power_model_formula": (
            "P_total = P_baseline + N_idle*P_idle + N_busy*P_busy; "
            "N_busy = ceil(sent_packets / demod_tx_capacity_per_step), bounded by allocated demods."
        ),
        "orbit_parameters": orbit_parameters,
        "one_orbit_seconds": orbit_period_s,
        "one_orbit_frames": int(one_orbit_frames),
        "one_orbit_track_frames_used": int(one_orbit_track_len),
        "coverage_trace_steps": int(len(trace_steps)),
        "coverage_step_country_csv": str(coverage_step_country_csv_path.resolve()),
        "ecdf_scope": ("active_steps" if any(int(r["sent_packets_sum"]) > 0 for r in step_metric_records) else "all_steps"),
        "coverage_model": coverage_info,
        "post_rotation_node_demod_check": node_demod_check,
        "covered_countries_count": int(len({(str(r["country"]), str(r["iso3"])) for r in all_records})),
        "reference_csv": str(reference_csv.resolve()),
        "country_csv_files": generated_country_csv,
        "country_avg_csv": country_avg_csv_path,
        "combined_plot_file": combined_plot_file,
        "stepwise_sent_vs_payload_plot_file": stepwise_sent_vs_payload_plot_file,
        "step_metrics_csv": step_metrics_csv_path,
        "collision_rate_ecdf_csv": collision_rate_ecdf_csv_path,
        "collision_rate_ecdf_plot_file": collision_ecdf_plot_file,
        "collision_rate_ecdf_by_elevation_csv": collision_rate_ecdf_by_elevation_csv_path,
        "collision_rate_ecdf_by_elevation_plot_file": collision_ecdf_by_elevation_plot_file,
        "collision_rate_power_plot_file": collision_rate_power_plot_file,
        "nodes_vs_decoded_payload_demod_csv": nodes_decoded_demod_csv_path,
        "nodes_vs_decoded_payload_demod_plot_file": nodes_decoded_demod_plot_file,
        "elevation_angle_ecdf_plot_file": elevation_plot_file,
        "elevation_angle_metrics_csv": elevation_metrics_file,
        "elevation_angle_aggregate_csv": elevation_aggregate_csv,
        "elevation_angle_aggregate_ecdf_plot_file": elevation_aggregate_ecdf_plot_file,
        "elevation_angle_aggregate_ecdf_csv": elevation_aggregate_ecdf_csv,
        "aggregate_csv": aggregate_csv_path,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "workflow_summary.json"
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("Workflow completed (stepwise reference-series LR-FHSS flow).")
    print(f"Summary:      {summary_path.resolve()}")
