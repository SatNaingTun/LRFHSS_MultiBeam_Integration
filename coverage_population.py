from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any, Mapping

import numpy as np

EARTH_RADIUS_M = 6_371_000.0
DEFAULT_POPULATION_DENSITY_PER_KM2 = 120.0


def _safe_float(value: Any, default: float) -> float:
    try:
        out = float(value)
        if math.isfinite(out):
            return out
    except (TypeError, ValueError):
        pass
    return float(default)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


def haversine_distance_m(lat1_deg: float, lon1_deg: float, lat2_deg: float, lon2_deg: float) -> float:
    lat1 = math.radians(lat1_deg)
    lon1 = math.radians(lon1_deg)
    lat2 = math.radians(lat2_deg)
    lon2 = math.radians(lon2_deg)

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    sin_dlat = math.sin(dlat / 2.0)
    sin_dlon = math.sin(dlon / 2.0)
    a = sin_dlat * sin_dlat + math.cos(lat1) * math.cos(lat2) * sin_dlon * sin_dlon
    c = 2.0 * math.atan2(math.sqrt(max(a, 0.0)), math.sqrt(max(1.0 - a, 0.0)))
    return float(EARTH_RADIUS_M * c)


def check_coverage_at_step(
    country_lat_deg: float,
    country_lon_deg: float,
    satellite_lat_deg: float,
    satellite_lon_deg: float,
    coverage_radius_m: float,
) -> tuple[bool, float]:
    distance_m = haversine_distance_m(
        lat1_deg=satellite_lat_deg,
        lon1_deg=satellite_lon_deg,
        lat2_deg=country_lat_deg,
        lon2_deg=country_lon_deg,
    )
    return bool(distance_m <= coverage_radius_m), float(distance_m)


def _country_equivalent_radius_m(area_km2: float | None, adult_population: int) -> float:
    if area_km2 is not None and float(area_km2) > 0.0:
        area_m2 = float(area_km2) * 1_000_000.0
    else:
        estimated_area_km2 = max(5_000.0, float(adult_population) / DEFAULT_POPULATION_DENSITY_PER_KM2)
        area_m2 = estimated_area_km2 * 1_000_000.0
    return float(math.sqrt(area_m2 / math.pi))


def _circle_intersection_area_m2(r1_m: float, r2_m: float, d_m: float) -> float:
    r1 = max(0.0, float(r1_m))
    r2 = max(0.0, float(r2_m))
    d = max(0.0, float(d_m))
    if r1 <= 0.0 or r2 <= 0.0:
        return 0.0
    if d >= r1 + r2:
        return 0.0
    if d <= abs(r1 - r2):
        return float(math.pi * min(r1, r2) ** 2)

    r1_sq = r1 * r1
    r2_sq = r2 * r2
    alpha = math.acos(max(-1.0, min(1.0, (d * d + r1_sq - r2_sq) / (2.0 * d * r1))))
    beta = math.acos(max(-1.0, min(1.0, (d * d + r2_sq - r1_sq) / (2.0 * d * r2))))
    term = max(0.0, (-d + r1 + r2) * (d + r1 - r2) * (d - r1 + r2) * (d + r1 + r2))
    return float(r1_sq * alpha + r2_sq * beta - 0.5 * math.sqrt(term))


def country_coverage_fraction(
    country_lat_deg: float,
    country_lon_deg: float,
    satellite_lat_deg: float,
    satellite_lon_deg: float,
    coverage_radius_m: float,
    country_area_km2: float | None,
    adult_population: int,
) -> tuple[float, float]:
    distance_m = haversine_distance_m(satellite_lat_deg, satellite_lon_deg, country_lat_deg, country_lon_deg)
    country_radius_m = _country_equivalent_radius_m(area_km2=country_area_km2, adult_population=adult_population)
    country_area_m2 = math.pi * country_radius_m * country_radius_m
    overlap_area_m2 = _circle_intersection_area_m2(r1_m=coverage_radius_m, r2_m=country_radius_m, d_m=distance_m)
    overlap_fraction = float(max(0.0, min(1.0, overlap_area_m2 / max(country_area_m2, 1e-12))))
    return overlap_fraction, float(distance_m)


def export_coverage_population_csv(
    input_csv: Path,
    output_csv: Path,
    params_config: Mapping[str, Any] | None,
    ground_track_lat_deg: np.ndarray | None = None,
    ground_track_lon_deg: np.ndarray | None = None,
    max_ground_track_points: int = 2000,
    trace_csv: Path | None = None,
    step_country_csv: Path | None = None,
    print_track_changes: bool = True,
    device_penetration_ratio: float = 0.001,
    devices_per_demodulator: int = 250,
) -> dict[str, Any]:
    if not input_csv.exists():
        raise FileNotFoundError(f"Coverage input CSV not found: {input_csv}")

    params_config = params_config or {}
    center_lat = _safe_float(params_config.get("latitude_center"), 35.6761919)
    center_lon = _safe_float(params_config.get("longitude_center"), 139.6503106)
    footprint_radius_m = _safe_float(params_config.get("r_footprint"), 100_000.0)
    centroid_buffer_radius_m = max(footprint_radius_m, 500_000.0)

    ratio = max(0.0, min(1.0, float(device_penetration_ratio)))
    demod_capacity = max(1, int(devices_per_demodulator))

    output_csv.parent.mkdir(parents=True, exist_ok=True)

    if ground_track_lat_deg is not None and ground_track_lon_deg is not None:
        # Read-only copies to guarantee coverage checks do not affect orbital rotation state.
        lat_track_full = np.array(ground_track_lat_deg, dtype=float, copy=True).reshape(-1)
        lon_track_full = np.array(ground_track_lon_deg, dtype=float, copy=True).reshape(-1)
        lat_track_full.setflags(write=False)
        lon_track_full.setflags(write=False)
        n_track = int(min(lat_track_full.size, lon_track_full.size))
        if n_track > 0:
            stride = int(max(1, math.ceil(n_track / max(1, int(max_ground_track_points)))))
            center_lats = lat_track_full[:n_track:stride]
            center_lons = lon_track_full[:n_track:stride]
        else:
            center_lats = np.array([center_lat], dtype=float)
            center_lons = np.array([center_lon], dtype=float)
    else:
        center_lats = np.array([center_lat], dtype=float)
        center_lons = np.array([center_lon], dtype=float)

    country_records: list[dict[str, Any]] = []
    total_rows = 0
    with input_csv.open("r", newline="", encoding="utf-8") as f_in:
        reader = csv.DictReader(f_in)
        for row in reader:
            total_rows += 1
            try:
                lat = float(row.get("latitude", ""))
                lon = float(row.get("longitude", ""))
            except (TypeError, ValueError):
                continue
            country_records.append(
                {
                    "country": row.get("country", ""),
                    "iso3": row.get("iso3", ""),
                    "latitude": float(lat),
                    "longitude": float(lon),
                    "adult_population_estimated": max(0, _safe_int(row.get("adult_population_estimated", ""), default=0)),
                    "area_km2": _safe_float(row.get("area_km2", ""), 0.0),
                }
            )

    if trace_csv is not None:
        trace_csv.parent.mkdir(parents=True, exist_ok=True)
        if step_country_csv is not None:
            step_country_csv.parent.mkdir(parents=True, exist_ok=True)
        with trace_csv.open("w", newline="", encoding="utf-8") as f_trace:
            trace_writer = csv.DictWriter(
                f_trace,
                fieldnames=[
                    "step",
                    "satellite_latitude",
                    "satellite_longitude",
                    "coverage_center_latitude",
                    "coverage_center_longitude",
                    "native_footprint_radius_m",
                    "footprint_radius_m",
                    "footprint_area_km2",
                    "covered_countries",
                    "covered_adult_population",
                    "estimated_devices_total",
                    "estimated_demodulators_total",
                ],
            )
            trace_writer.writeheader()
            step_country_writer = None
            f_step_country = None
            if step_country_csv is not None:
                f_step_country = step_country_csv.open("w", newline="", encoding="utf-8")
                step_country_writer = csv.DictWriter(
                    f_step_country,
                    fieldnames=[
                        "step",
                        "satellite_latitude",
                        "satellite_longitude",
                        "native_footprint_radius_m",
                        "footprint_radius_m",
                        "footprint_area_km2",
                        "country",
                        "iso3",
                        "overlap_fraction",
                        "effective_population",
                        "population_coverage_share",
                        "step_effective_population",
                        "step_devices_total",
                        "step_demodulators_total",
                    ],
                )
                step_country_writer.writeheader()

            try:
                for idx, (c_lat, c_lon) in enumerate(zip(center_lats, center_lons)):
                    step_covered_countries = 0
                    step_covered_adult_pop = 0
                    step_effective_population = 0.0
                    step_country_overlaps: list[dict[str, Any]] = []
                    for country in country_records:
                        overlap_fraction, _ = country_coverage_fraction(
                            country_lat_deg=float(country["latitude"]),
                            country_lon_deg=float(country["longitude"]),
                            satellite_lat_deg=float(c_lat),
                            satellite_lon_deg=float(c_lon),
                            coverage_radius_m=centroid_buffer_radius_m,
                            country_area_km2=float(country.get("area_km2", 0.0)),
                            adult_population=int(country["adult_population_estimated"]),
                        )
                        if overlap_fraction > 0.0:
                            adult_pop = int(country["adult_population_estimated"])
                            effective_pop = float(adult_pop) * float(overlap_fraction)
                            step_covered_countries += 1
                            step_covered_adult_pop += adult_pop
                            step_effective_population += effective_pop
                            step_country_overlaps.append(
                                {
                                    "country": str(country["country"]),
                                    "iso3": str(country["iso3"]),
                                    "overlap_fraction": float(overlap_fraction),
                                    "effective_population": float(effective_pop),
                                }
                            )

                    step_estimated_devices = int(round(step_effective_population * ratio))
                    step_estimated_demods = (
                        int(math.ceil(step_estimated_devices / demod_capacity)) if step_estimated_devices > 0 else 0
                    )
                    footprint_area_km2 = float(math.pi * centroid_buffer_radius_m * centroid_buffer_radius_m / 1_000_000.0)

                    trace_writer.writerow(
                        {
                            "step": int(idx),
                            "satellite_latitude": f"{float(c_lat):.6f}",
                            "satellite_longitude": f"{float(c_lon):.6f}",
                            "coverage_center_latitude": f"{float(c_lat):.6f}",
                            "coverage_center_longitude": f"{float(c_lon):.6f}",
                            "native_footprint_radius_m": float(footprint_radius_m),
                            "footprint_radius_m": float(centroid_buffer_radius_m),
                            "footprint_area_km2": float(footprint_area_km2),
                            "covered_countries": int(step_covered_countries),
                            "covered_adult_population": int(step_covered_adult_pop),
                            "estimated_devices_total": int(step_estimated_devices),
                            "estimated_demodulators_total": int(step_estimated_demods),
                        }
                    )

                    if step_country_writer is not None and step_effective_population > 0.0:
                        for c in step_country_overlaps:
                            share = float(c["effective_population"]) / float(step_effective_population)
                            step_country_writer.writerow(
                                {
                                    "step": int(idx),
                                    "satellite_latitude": f"{float(c_lat):.6f}",
                                    "satellite_longitude": f"{float(c_lon):.6f}",
                                    "native_footprint_radius_m": float(footprint_radius_m),
                                    "footprint_radius_m": float(centroid_buffer_radius_m),
                                    "footprint_area_km2": float(footprint_area_km2),
                                    "country": c["country"],
                                    "iso3": c["iso3"],
                                    "overlap_fraction": float(c["overlap_fraction"]),
                                    "effective_population": float(c["effective_population"]),
                                    "population_coverage_share": float(max(0.0, min(1.0, share))),
                                    "step_effective_population": float(step_effective_population),
                                    "step_devices_total": int(step_estimated_devices),
                                    "step_demodulators_total": int(step_estimated_demods),
                                }
                            )

                    if print_track_changes:
                        print(
                            f"[CoverageTrack] step={idx} "
                            f"sat=({float(c_lat):.6f}, {float(c_lon):.6f}) "
                            f"center=({float(c_lat):.6f}, {float(c_lon):.6f}) "
                            f"demods={step_estimated_demods}"
                        )
            finally:
                if f_step_country is not None:
                    f_step_country.close()

    covered_rows: list[dict[str, Any]] = []
    for country in country_records:
        lat = float(country["latitude"])
        lon = float(country["longitude"])
        adult_population = int(country["adult_population_estimated"])
        country_area_km2 = float(country.get("area_km2", 0.0))
        best_step = -1
        best_overlap_fraction = 0.0
        best_distance_m = float("inf")
        for step_idx, (c_lat, c_lon) in enumerate(zip(center_lats, center_lons)):
            overlap_fraction, step_distance_m = country_coverage_fraction(
                country_lat_deg=lat,
                country_lon_deg=lon,
                satellite_lat_deg=float(c_lat),
                satellite_lon_deg=float(c_lon),
                coverage_radius_m=centroid_buffer_radius_m,
                country_area_km2=country_area_km2,
                adult_population=adult_population,
            )
            if overlap_fraction > best_overlap_fraction:
                best_overlap_fraction = float(overlap_fraction)
                best_step = int(step_idx)
                best_distance_m = float(step_distance_m)
            elif overlap_fraction == best_overlap_fraction and step_distance_m < best_distance_m:
                best_step = int(step_idx)
                best_distance_m = float(step_distance_m)

        if best_step >= 0:
            distance_m = best_distance_m
            in_coverage = bool(best_overlap_fraction > 0.0)
            nearest_center_lat = float(center_lats[best_step])
            nearest_center_lon = float(center_lons[best_step])
        else:
            distance_m = haversine_distance_m(center_lat, center_lon, lat, lon)
            in_coverage = distance_m <= centroid_buffer_radius_m
            nearest_center_lat = float(center_lat)
            nearest_center_lon = float(center_lon)
            best_overlap_fraction = 1.0 if in_coverage else 0.0

        if not in_coverage:
            continue

        covered_adult_population = int(round(adult_population * best_overlap_fraction))
        estimated_devices = int(round(covered_adult_population * ratio))
        estimated_demodulators = int(math.ceil(estimated_devices / demod_capacity)) if estimated_devices > 0 else 0

        covered_rows.append(
            {
                "country": country["country"],
                "iso3": country["iso3"],
                "latitude": f"{lat:.6f}",
                "longitude": f"{lon:.6f}",
                "adult_population_estimated": adult_population,
                "area_km2": f"{country_area_km2:.3f}" if country_area_km2 > 0.0 else "",
                "overlap_fraction": float(best_overlap_fraction),
                "covered_adult_population_estimated": int(covered_adult_population),
                "distance_to_coverage_center_m": int(round(distance_m)),
                "nearest_coverage_step": int(best_step),
                "coverage_radius_m": int(round(centroid_buffer_radius_m)),
                "in_coverage": True,
                "assumed_device_penetration_ratio": ratio,
                "estimated_devices": estimated_devices,
                "assumed_devices_per_demodulator": demod_capacity,
                "estimated_demodulators": estimated_demodulators,
                "coverage_center_latitude": f"{nearest_center_lat:.6f}",
                "coverage_center_longitude": f"{nearest_center_lon:.6f}",
            }
        )

    if covered_rows:
        total_weight = 0.0
        for row in covered_rows:
            covered_population = float(row["covered_adult_population_estimated"])
            coverage_strength = float(row["overlap_fraction"])
            weighted_population = covered_population
            row["coverage_strength"] = float(coverage_strength)
            row["weighted_population"] = float(weighted_population)
            total_weight += weighted_population

        if total_weight <= 0.0:
            total_weight = float(len(covered_rows))
            for row in covered_rows:
                row["weighted_population"] = 1.0
                row["coverage_strength"] = 0.0

        total_demodulators = int(sum(int(r["estimated_demodulators"]) for r in covered_rows))
        provisional: list[tuple[int, float]] = []
        assigned = 0
        for idx, row in enumerate(covered_rows):
            share = float(row["weighted_population"]) / total_weight
            raw_demods = share * total_demodulators
            demods_floor = int(math.floor(raw_demods))
            row["population_coverage_share"] = float(share)
            row["estimated_demodulators_proportional"] = demods_floor
            provisional.append((idx, raw_demods - demods_floor))
            assigned += demods_floor

        remaining = max(0, total_demodulators - assigned)
        for idx, _ in sorted(provisional, key=lambda x: x[1], reverse=True)[:remaining]:
            covered_rows[idx]["estimated_demodulators_proportional"] = int(
                covered_rows[idx]["estimated_demodulators_proportional"] + 1
            )

    with output_csv.open("w", newline="", encoding="utf-8") as f_out:
        fieldnames = [
            "country",
            "iso3",
            "latitude",
            "longitude",
            "adult_population_estimated",
            "area_km2",
            "overlap_fraction",
            "covered_adult_population_estimated",
            "distance_to_coverage_center_m",
            "nearest_coverage_step",
            "coverage_radius_m",
            "in_coverage",
            "assumed_device_penetration_ratio",
            "estimated_devices",
            "assumed_devices_per_demodulator",
            "estimated_demodulators",
            "coverage_strength",
            "weighted_population",
            "population_coverage_share",
            "estimated_demodulators_proportional",
            "coverage_center_latitude",
            "coverage_center_longitude",
        ]
        writer = csv.DictWriter(f_out, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(covered_rows)

    total_adult_population_covered = int(sum(int(r["covered_adult_population_estimated"]) for r in covered_rows))
    total_devices = int(sum(int(r["estimated_devices"]) for r in covered_rows))
    total_demodulators = int(sum(int(r["estimated_demodulators"]) for r in covered_rows))

    return {
        "input_csv": str(input_csv.resolve()),
        "output_csv": str(output_csv.resolve()),
        "trace_csv": str(trace_csv.resolve()) if trace_csv is not None else None,
        "coverage_center_latitude": center_lat,
        "coverage_center_longitude": center_lon,
        "coverage_radius_m": centroid_buffer_radius_m,
        "native_footprint_radius_m": footprint_radius_m,
        "country_centroid_buffer_applied": bool(centroid_buffer_radius_m > footprint_radius_m),
        "coverage_mode": "moving_ground_track" if center_lats.size > 1 else "single_center",
        "ground_track_points_used": int(center_lats.size),
        "device_penetration_ratio": ratio,
        "devices_per_demodulator": demod_capacity,
        "countries_total": int(total_rows),
        "countries_in_coverage": int(len(covered_rows)),
        "adult_population_in_coverage": total_adult_population_covered,
        "estimated_devices_total": total_devices,
        "estimated_demodulators_total": total_demodulators,
    }
