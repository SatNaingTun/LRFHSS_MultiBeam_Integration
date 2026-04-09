import csv
import json
import random
import re
from pathlib import Path

import numpy as np

from coverage_population import export_coverage_population_csv
from lrfhss_communication import build_comparison_series, list_available_demod_counts
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
                    "estimated_devices_total": max(0, int(float(row.get("estimated_devices_total", 0) or 0))),
                    "estimated_demodulators_total": max(0, int(float(row.get("estimated_demodulators_total", 0) or 0))),
                }
            )
    return rows


def _check_nodes_and_demods_for_coverage(
    node_loads: list[int],
    demodulator_options: list[int],
    coverage_info: dict,
) -> dict:
    coverage_devices = max(0, int(coverage_info.get("estimated_devices_total", 0)))
    coverage_demods = max(0, int(coverage_info.get("estimated_demodulators_total", 0)))

    in_coverage_nodes = [v for v in node_loads if v <= coverage_devices]
    out_of_coverage_nodes = [v for v in node_loads if v > coverage_devices]
    in_coverage_demods = [v for v in demodulator_options if v <= coverage_demods]
    out_of_coverage_demods = [v for v in demodulator_options if v > coverage_demods]

    check = {
        "status": "ok",
        "coverage_constraints": {
            "countries_in_coverage": int(coverage_info.get("countries_in_coverage", 0)),
            "estimated_devices_total": coverage_devices,
            "estimated_demodulators_total": coverage_demods,
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


def plot_country_sent_vs_payload(records: list[dict], out_png: Path, title: str) -> None:
    if plt is None:
        raise ModuleNotFoundError("matplotlib is required for plotting. Install with: pip install matplotlib")
    if not records:
        return

    grouped: dict[int, list[float]] = {}
    for row in records:
        sent_packets = int(float(row.get("selected_nodes", 0) or 0))
        decoded_payload = float(row.get("decoded_payload_mean", 0.0) or 0.0)
        if sent_packets <= 0:
            continue
        grouped.setdefault(sent_packets, []).append(decoded_payload)
    if not grouped:
        return

    xs = np.array(sorted(grouped.keys()), dtype=float)
    ys = np.array([float(np.mean(grouped[int(x)])) for x in xs], dtype=float)

    fig, ax = plt.subplots(figsize=(10, 8))
    ax.plot(xs, ys, color="#1f77b4", linewidth=2, marker="o", label="decoded payloads")
    ax.plot(xs, xs, color="black", linewidth=1.8, label="x=y")
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

