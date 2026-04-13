import csv
import json
from pathlib import Path
from random import random
import numpy as np
from tqdm import tqdm
import random
from coverage_population import export_coverage_population_csv
from workflow_tasks.lrfhss_communication import build_comparison_series, list_available_demod_counts
from multi_beam_connector import load_multi_beam_modules
from workflow_tasks.lrfhss_flowtask import _build_node_loads, _check_nodes_and_demods_for_coverage, _extract_series_value_for_nodes, _load_covered_countries, _load_trace_steps, _normalize_demods, _sanitize_filename, _stable_country_hash, plot_country_sent_vs_payload, _select_available_demod
from workflow_tasks.orbit_visibility import compute_orbit_parameters, compute_satellite_orbit

__all__ = ["run_workflow"]



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
):
    del lrfhss_root, runs_per_point
    node_loads = _build_node_loads(node_min=node_min, node_max=node_max, node_points=node_points, nodes_list=nodes_list)
    demods = _normalize_demods(demodulator_options)
    available_reference_demods = list_available_demod_counts(reference_csv=reference_csv, coding_rate=1, family="driver")
    if not available_reference_demods:
        raise ValueError(f"No available demod rows found in reference CSV: {reference_csv}")

    _, network_geometry, params_mod, _, simulation = load_multi_beam_modules(multi_beam_root)
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
    lat_raw = orbit_task_info.get("satellite_ground_track_lat_deg")
    lon_raw = orbit_task_info.get("satellite_ground_track_lon_deg")
    if lat_raw is None or lon_raw is None:
        raise ValueError("Orbit rotation did not provide ground-track arrays.")
    lat = np.array(lat_raw, dtype=float, copy=True)
    lon = np.array(lon_raw, dtype=float, copy=True)
    one_orbit_track_len = int(min(one_orbit_frames, min(lat.size, lon.size)))

    coverage_info = export_coverage_population_csv(
        input_csv=Path("Data") / "adult_population_country_coordinates.csv",
        output_csv=coverage_csv_path,
        params_config=params_config,
        ground_track_lat_deg=lat[:one_orbit_track_len],
        ground_track_lon_deg=lon[:one_orbit_track_len],
        max_ground_track_points=2000,
        trace_csv=coverage_trace_csv_path,
        print_track_changes=True,
        device_penetration_ratio=0.001,
        devices_per_demodulator=250,
    )

    node_demod_check = _check_nodes_and_demods_for_coverage(node_loads=node_loads, demodulator_options=demods, coverage_info=coverage_info)
    filtered_nodes = node_demod_check["node_count_options_in_coverage"]
    filtered_demods = node_demod_check["demod_count_options_in_coverage"]
    if not filtered_nodes or not filtered_demods:
        raise ValueError("No node/demod options remain after coverage filtering.")

    covered_countries = _load_covered_countries(coverage_csv_path=coverage_csv_path)
    trace_steps = _load_trace_steps(trace_csv_path=coverage_trace_csv_path)
    if not trace_steps:
        raise ValueError("No coverage trace steps found for one-orbit simulation.")

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
    ]
    all_records: list[dict] = []
    country_records_map: dict[tuple[str, str], list[dict]] = {}
    generated_country_csv: list[str] = []
    combined_plot_file: str | None = None

    series_cache: dict[int, any] = {}

    with aggregate_csv.open("w", encoding="utf-8", newline="") as f_step:
        writer = csv.DictWriter(f_step, fieldnames=step_fieldnames)
        writer.writeheader()

        step_iter = tqdm(trace_steps, desc="Rotation steps", unit="step") if tqdm is not None else trace_steps
        for step_row in step_iter:
            step_idx = int(step_row["step"])
            step_devices_total = int(step_row["estimated_devices_total"])
            step_demods_total = int(step_row["estimated_demodulators_total"])

            country_iter = (
                tqdm(covered_countries, desc=f"Countries@step{step_idx}", unit="country", leave=False)
                if tqdm is not None
                else covered_countries
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

                # Time-step-seeded selection: reproducible for same --seed, but varies by step/country.
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

                row = {
                    "country": country_name,
                    "iso3": iso3,
                    "step": step_idx,
                    "satellite_latitude": float(step_row["satellite_latitude"]),
                    "satellite_longitude": float(step_row["satellite_longitude"]),
                    "country_share": float(share),
                    "step_devices_total": int(step_devices_total),
                    "step_demods_total": int(step_demods_total),
                    "selected_nodes": int(selected_nodes),
                    "selected_demods": int(selected_demods),
                    "series_demod_used": int(series_demod),
                    "sent_packets_used": int(sent_packets_used),
                    "decoded_payload_base": float(decoded_base),
                    "decoded_payload_mean": float(decoded_earlydd),
                }
                writer.writerow(row)
                f_step.flush()
                all_records.append(row)
                country_records_map.setdefault((country_name, iso3), []).append(row)

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
            grouped.setdefault(key, {"sent_packets_used": [], "decoded_payload_mean": []})
            grouped[key]["sent_packets_used"].append(float(row["sent_packets_used"]))
            grouped[key]["decoded_payload_mean"].append(float(row["decoded_payload_mean"]))

        country_avg_records: list[dict] = []
        for (country_name, iso3), vals in sorted(grouped.items()):
            country_avg_records.append(
                {
                    "country": country_name,
                    "iso3": iso3,
                    "selected_nodes": float(np.mean(np.array(vals["sent_packets_used"], dtype=float))),
                    "decoded_payload_mean": float(np.mean(np.array(vals["decoded_payload_mean"], dtype=float))),
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
        aggregate_csv_path = str(aggregate_csv.resolve())
    else:
        aggregate_csv_path = None
        country_avg_csv_path = None

    summary = {
        "workflow": [
            "Propagate Kepler rotation",
            "At each rotation step derive nodes/demods from coverage",
            "Call build_comparison_series and write stepwise LR-FHSS rows",
            "After rotation aggregate by country and export final plot",
            "END",
        ],
        "mode": "rotation_stepwise_reference_series_lrfhss",
        "orbit_task": orbit_task_info["orbit_task"],
        "orbit_parameters": orbit_parameters,
        "one_orbit_seconds": orbit_period_s,
        "one_orbit_frames": int(one_orbit_frames),
        "one_orbit_track_frames_used": int(one_orbit_track_len),
        "coverage_trace_steps": int(len(trace_steps)),
        "coverage_model": coverage_info,
        "post_rotation_node_demod_check": node_demod_check,
        "covered_countries_count": int(len(covered_countries)),
        "reference_csv": str(reference_csv.resolve()),
        "country_csv_files": generated_country_csv,
        "country_avg_csv": country_avg_csv_path,
        "combined_plot_file": combined_plot_file,
        "aggregate_csv": aggregate_csv_path,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "workflow_summary.json"
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("Workflow completed (stepwise reference-series LR-FHSS flow).")
    print(f"Summary:      {summary_path.resolve()}")
