import json
from pathlib import Path

import numpy as np

from coverage_population import export_coverage_population_csv
from multi_beam_connector import load_multi_beam_modules
from workflow_flow.orbit_visibility import compute_orbit_parameters, compute_satellite_orbit

__all__ = ["run_workflow"]


def _build_node_loads(node_min: int, node_max: int, node_points: int, nodes_list: list[int] | None) -> list[int]:
    if nodes_list:
        loads = sorted(set(int(v) for v in nodes_list if int(v) >= 0))
    else:
        if node_min <= 0 or node_max <= 0:
            raise ValueError("node_min and node_max must be positive when --nodes is not provided.")
        points = max(1, int(node_points))
        loads = [int(round(v)) for v in np.logspace(np.log10(node_min), np.log10(node_max), num=points)]
        loads = sorted(set(v for v in loads if v >= 0))
    if not loads:
        raise ValueError("Node check failed: provide at least one non-negative node count.")
    return loads


def _normalize_demods(demodulator_options: list[int]) -> list[int]:
    demods = sorted(set(int(v) for v in demodulator_options if int(v) > 0))
    if not demods:
        raise ValueError("Demod check failed: provide at least one positive demodulator count.")
    return demods


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
        "node_min": int(min(node_loads)),
        "node_max": int(max(node_loads)),
        "demod_min": int(min(demodulator_options)),
        "demod_max": int(max(demodulator_options)),
    }
    print(
        "Post-rotation coverage check: "
        f"devices={coverage_devices}, demods={coverage_demods}, "
        f"nodes_in_coverage={len(in_coverage_nodes)}/{len(node_loads)}, "
        f"demods_in_coverage={len(in_coverage_demods)}/{len(demodulator_options)}"
    )
    return check


def run_workflow(
    multi_beam_root: Path,
    output_dir: Path,
    seed: int,
    node_min: int,
    node_max: int,
    node_points: int,
    demodulator_options: list[int],
    nodes_list: list[int] | None,
    scenario_steps: int = 120,
    step_seconds: float = 228.0,
):
    node_loads = _build_node_loads(node_min=node_min, node_max=node_max, node_points=node_points, nodes_list=nodes_list)
    demods = _normalize_demods(demodulator_options)

    _, network_geometry, params_mod, _ = load_multi_beam_modules(multi_beam_root)

    sat_pos, orbit_task_info = compute_satellite_orbit(
        network_geometry=network_geometry,
        params_mod=params_mod,
        step_seconds=float(step_seconds),
        scenario_steps=max(1, int(scenario_steps)),
    )
    orbit_parameters = compute_orbit_parameters(
        sat_pos=sat_pos,
        step_seconds=orbit_task_info["orbit_task"]["orbit_config"]["time_step_s"],
    )

    params_config = params_mod.read_params() if params_mod is not None and hasattr(params_mod, "read_params") else {}
    coverage_csv_path = output_dir.parent / "csv" / "coverage_population_devices.csv"
    coverage_trace_csv_path = output_dir.parent / "csv" / "coverage_track_trace.csv"
    ground_track_lat = orbit_task_info.get("satellite_ground_track_lat_deg")
    ground_track_lon = orbit_task_info.get("satellite_ground_track_lon_deg")
    coverage_info = export_coverage_population_csv(
        input_csv=Path("Data") / "adult_population_country_coordinates.csv",
        output_csv=coverage_csv_path,
        params_config=params_config,
        ground_track_lat_deg=np.array(ground_track_lat, copy=True) if ground_track_lat is not None else None,
        ground_track_lon_deg=np.array(ground_track_lon, copy=True) if ground_track_lon is not None else None,
        max_ground_track_points=2000,
        trace_csv=coverage_trace_csv_path,
        print_track_changes=True,
        device_penetration_ratio=0.001,
        devices_per_demodulator=250,
    )

    node_demod_check = _check_nodes_and_demods_for_coverage(
        node_loads=node_loads,
        demodulator_options=demods,
        coverage_info=coverage_info,
    )

    summary = {
        "workflow": [
            "Propagate Kepler rotation",
            "Estimate coverage from rotated ground track",
            "Check node and demod options constrained by covered satellite locations",
            "END",
        ],
        "mode": "rotation_coverage_node_demod_checks_only",
        "seed": int(seed),
        "orbit_task": orbit_task_info["orbit_task"],
        "orbit_parameters": orbit_parameters,
        "coverage_model": coverage_info,
        "post_rotation_node_demod_check": node_demod_check,
        "scenario_steps": int(scenario_steps),
        "step_seconds": float(step_seconds),
        "node_range": {"min": int(node_min), "max": int(node_max), "points": int(node_points)},
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "workflow_summary.json"
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("Workflow completed (rotation + coverage + node/demod checks only).")
    print(f"Summary:      {summary_path.resolve()}")
