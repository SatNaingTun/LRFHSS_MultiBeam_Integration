import csv
import json
import random
import re
from pathlib import Path

import numpy as np

from coverage_population import export_coverage_population_csv
from .lrfhss_communication import build_comparison_series, list_available_demod_counts
from multi_beam_connector import load_multi_beam_modules
from workflow_tasks.orbit_visibility import compute_orbit_parameters, compute_satellite_orbit

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


def _build_node_loads(node_min: int, node_max: int, node_points: int, nodes_list: list[int] | None) -> list[int]:
    if nodes_list:
        loads = sorted(set(int(v) for v in nodes_list if int(v) > 0))
    else:
        if node_min <= 0 or node_max <= 0:
            raise ValueError("node_min and node_max must be positive when --nodes is not provided.")
        points = max(1, int(node_points))
        loads = [int(round(v)) for v in np.logspace(np.log10(node_min), np.log10(node_max), num=points)]
        loads = sorted(set(v for v in loads if v > 0))
    if not loads:
        raise ValueError("Node check failed: provide at least one positive node count.")
    return loads


def _normalize_demods(demodulator_options: list[int]) -> list[int]:
    demods = sorted(set(int(v) for v in demodulator_options if int(v) > 0))
    if not demods:
        raise ValueError("Demod check failed: provide at least one positive demodulator count.")
    return demods


def _sanitize_filename(value: str) -> str:
    out = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return out.strip("_") or "country"


def _load_covered_countries(coverage_csv_path: Path) -> list[dict]:
    covered: list[dict] = []
    with coverage_csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            in_cov = str(row.get("in_coverage", "")).strip().lower()
            if in_cov not in {"1", "true", "yes"}:
                continue
            share = float(row.get("population_coverage_share", 0.0) or 0.0)
            covered.append(
                {
                    "country": str(row.get("country", "")).strip(),
                    "iso3": str(row.get("iso3", "")).strip(),
                    "population_coverage_share": max(0.0, share),
                }
            )
    return covered


def _load_trace_steps(trace_csv_path: Path) -> list[dict]:
    rows: list[dict] = []
    with trace_csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(
                {
                    "step": int(float(row.get("step", 0) or 0)),
                    "satellite_latitude": float(row.get("satellite_latitude", 0.0) or 0.0),
                    "satellite_longitude": float(row.get("satellite_longitude", 0.0) or 0.0),
                    "native_footprint_radius_m": float(row.get("native_footprint_radius_m", 0.0) or 0.0),
                    "footprint_radius_m": float(row.get("footprint_radius_m", 0.0) or 0.0),
                    "footprint_area_km2": float(row.get("footprint_area_km2", 0.0) or 0.0),
                    "estimated_devices_total": max(0, int(float(row.get("estimated_devices_total", 0) or 0))),
                    "estimated_demodulators_total": max(0, int(float(row.get("estimated_demodulators_total", 0) or 0))),
                }
            )
    return rows


def _check_nodes_and_demods_for_coverage(
    node_loads: list[int],
    demodulator_options: list[int],
    coverage_info: dict,
    onboard_demods: int | None = None,
) -> dict:
    coverage_devices = max(0, int(coverage_info.get("estimated_devices_total", 0)))
    coverage_demods_estimated = max(0, int(coverage_info.get("estimated_demodulators_total", 0)))
    hardware_demods = (
        max(0, int(onboard_demods))
        if onboard_demods is not None
        else coverage_demods_estimated
    )

    in_coverage_nodes = [v for v in node_loads if v <= coverage_devices]
    out_of_coverage_nodes = [v for v in node_loads if v > coverage_devices]
    in_coverage_demods = [v for v in demodulator_options if v <= hardware_demods]
    out_of_coverage_demods = [v for v in demodulator_options if v > hardware_demods]

    check = {
        "status": "ok",
        "coverage_constraints": {
            "countries_in_coverage": int(coverage_info.get("countries_in_coverage", 0)),
            "estimated_devices_total": coverage_devices,
            "estimated_demodulators_total": coverage_demods_estimated,
            "hardware_demodulators_total": hardware_demods,
        },
        "node_count_options": node_loads,
        "node_count_options_in_coverage": in_coverage_nodes,
        "node_count_options_out_of_coverage": out_of_coverage_nodes,
        "demod_count_options": demodulator_options,
        "demod_count_options_in_coverage": in_coverage_demods,
        "demod_count_options_out_of_coverage": out_of_coverage_demods,
    }
    return check


def _select_available_demod(requested_demod: int, available_demods: list[int]) -> int | None:
    eligible = [d for d in available_demods if d <= int(requested_demod)]
    if eligible:
        return int(max(eligible))
    return None


def _extract_series_value_for_nodes(series, target_nodes: int) -> tuple[int, float, float]:
    nodes = np.array(series.nodes, dtype=float)
    idx = int(np.argmin(np.abs(nodes - float(target_nodes))))
    sent = int(round(float(nodes[idx])))
    base_val = float(series.driver_base[idx])
    earlydd_val = float(series.driver_earlydd[idx])
    return sent, base_val, earlydd_val


def _stable_country_hash(country: str, iso3: str) -> int:
    key = f"{country}|{iso3}"
    # Stable (cross-run) hash instead of Python's randomized hash().
    return int(sum((idx + 1) * ord(ch) for idx, ch in enumerate(key)))


def plot_country_sent_vs_payload(
    records: list[dict],
    out_png: Path,
    title: str,
    aggregate_by_sent: bool = True,
) -> None:
    if plt is None:
        raise ModuleNotFoundError("matplotlib is required for plotting. Install with: pip install matplotlib")
    if not records:
        return

    fig, ax = plt.subplots(figsize=(10, 8))
    series_specs = [
        ("decoded_payload_base", "baseline decoded payload", "#ff7f0e", "o"),
        ("decoded_payload_early_decode_drop", "early decode + early drop", "#1f77b4", "s"),
    ]
    if not any(any(key in row for key, _, _, _ in series_specs) for row in records):
        series_specs = [
            ("decoded_payload_mean", "decoded payloads", "#1f77b4", "o"),
        ]
    if aggregate_by_sent:
        grouped: dict[int, dict[str, list[float]]] = {}
        for row in records:
            sent_packets = int(float(row.get("selected_nodes", 0) or 0))
            if sent_packets <= 0:
                continue
            entry = grouped.setdefault(sent_packets, {})
            for key, _, _, _ in series_specs:
                if key not in row:
                    continue
                entry.setdefault(key, []).append(float(row.get(key, 0.0) or 0.0))
        if not grouped:
            plt.close(fig)
            return
        xs = np.array(sorted(grouped.keys()), dtype=float)
        plotted = 0
        for key, label, color, marker in series_specs:
            if not any(key in grouped[int(x)] for x in xs):
                continue
            ys = np.array(
                [
                    float(np.mean(grouped[int(x)].get(key, [np.nan])))
                    for x in xs
                ],
                dtype=float,
            )
            if np.all(np.isnan(ys)):
                continue
            if xs.size == 1:
                ax.scatter(
                    xs,
                    ys,
                    color=color,
                    marker=marker,
                    s=52,
                    edgecolors="white",
                    linewidths=0.8,
                    zorder=4,
                    label=label,
                )
            else:
                ax.plot(
                    xs,
                    ys,
                    color=color,
                    linewidth=2,
                    marker=marker,
                    markersize=4,
                    markeredgecolor="white",
                    markeredgewidth=0.6,
                    zorder=3,
                    label=label,
                )
            plotted += 1
        if plotted <= 0:
            plt.close(fig)
            return
    else:
        line_series: dict[str, tuple[list[float], list[float], str, str]] = {}
        for key, label, color, marker in series_specs:
            line_series[key] = ([], [], color, marker)
        for row in records:
            sent_packets = int(float(row.get("selected_nodes", 0) or 0))
            if sent_packets <= 0:
                continue
            for key, _, _, _ in series_specs:
                if key not in row:
                    continue
                xs_list, ys_list, _, _ = line_series[key]
                xs_list.append(float(sent_packets))
                ys_list.append(float(row.get(key, 0.0) or 0.0))
        if not any(xs for xs, _, _, _ in line_series.values()):
            plt.close(fig)
            return
        first_key = next(key for key, (xs_list, _, _, _) in line_series.items() if xs_list)
        xs = np.array(line_series[first_key][0], dtype=float)
        for key, label, color, marker in series_specs:
            xs_list, ys_list, _, _ = line_series[key]
            if not xs_list:
                continue
            grouped_xy: dict[float, list[float]] = {}
            for x_val, y_val in zip(xs_list, ys_list):
                grouped_xy.setdefault(float(x_val), []).append(float(y_val))
            xs_sorted = np.array(sorted(grouped_xy.keys()), dtype=float)
            ys_mean = np.array(
                [float(np.mean(np.array(grouped_xy[x_val], dtype=float))) for x_val in xs_sorted],
                dtype=float,
            )
            if xs_sorted.size == 1:
                ax.scatter(
                    xs_sorted,
                    ys_mean,
                    color=color,
                    marker=marker,
                    s=52,
                    edgecolors="white",
                    linewidths=0.8,
                    zorder=4,
                    label=label,
                )
            else:
                ax.plot(
                    xs_sorted,
                    ys_mean,
                    color=color,
                    linewidth=2,
                    marker=marker,
                    markersize=4,
                    markeredgecolor="white",
                    markeredgewidth=0.6,
                    alpha=0.95,
                    zorder=3,
                    label=label,
                )

    diag_min = float(max(1.0, np.nanmin(xs))) if xs.size else 1.0
    diag_max = float(max(diag_min * 1.01, np.nanmax(xs))) if xs.size else diag_min * 1.01
    ax.plot(
        [diag_min, diag_max],
        [diag_min, diag_max],
        color="black",
        linewidth=1.6,
        alpha=0.85,
        zorder=1,
        label="x=y",
    )
    ax.set_title(title, fontsize=16)
    ax.set_xlabel("Sent packets", fontsize=14)
    ax.set_ylabel("Number of Decoded Payloads", fontsize=14)
    ax.set_xscale("log")
    ax.grid(True, which="both", linestyle="-", linewidth=0.5, alpha=0.4)
    ax.legend(fontsize=10, loc="best")
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=220)
    plt.close(fig)
