from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import sys
from datetime import datetime, timezone, timedelta
from typing import Any

import numpy as np

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    plt = None

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from coverage_population import haversine_distance_m
from leo_kepler_rotation import run_leo_orbit_rotation_task
from orbit_formula import compute_horizon_central_angle_rad
from ProjectConfig import (
    EARTRH_R,
    LATITUDE_CENTER_DEG,
    LONGITUDE_CENTER_DEG,
    R_FOOTPRINT,
    SAT_H,
    T_FRAME,
    V_SATELLITE,
    node_population_ratio,
    demd_population_ratio,
    baseline_power,
    idle_demodulator_power,
    busy_demodulator_power,
    elev_list)


class SatelliteStepper:
    """
    Step-wise satellite tracker with Kepler-aligned orbit propagation.

    - get_pos(): current satellite position/state
    - get_footprint(): footprint radius derived from current satellite position
    - next(): advance one logical step and append one CSV row
    """
    BASE_CSV_FIELDNAMES = [
        "step",
        "orbit_index",
        "timestamp_s",
        "orbit_timestamp_s",
        "timestamp_utc",
        "sat_x_m",
        "sat_y_m",
        "sat_z_m",
        "sat_radius_m",
        "node_population_ratio",
        "calculated_nodes",
        "calculated_demodulators",
    ]

    def __init__(
        self,
        output_csv_path: str | Path,
        population_csv_path: str | Path = "Data/csv/population_data.csv",
        ocean_csv_path: str | Path = "Data/csv/ocean_data.csv",
        current_pos_json_path: str | Path | None = None,
        groundtrack_coverage_csv_path: str | Path | None = None,
        elevation_states_csv_path: str | Path | None = None,
        node_population_ratio: float = 0.0001,
        demd_population_ratio: int = demd_population_ratio,
        minimum_frames: int = 720,
        simulation_start_utc: datetime | str | None = None,
        user_position_seed: int = 42,
        elev_list: list[float] | None = elev_list,
        demod_activity_ratio: float = 0.1,
        demod_sleep_ratio: float = 0.3,
        baseline_power_w: float = baseline_power,
        idle_demodulator_power_w: float = idle_demodulator_power,
        busy_demodulator_power_w: float = busy_demodulator_power,
    ) -> None:
        self.output_csv_path = Path(output_csv_path)
        self.population_csv_path = Path(population_csv_path)
        self.ocean_csv_path = Path(ocean_csv_path)
        if current_pos_json_path is None:
            self.current_pos_json_path = self.output_csv_path.with_name(f"{self.output_csv_path.stem}_current_pos.json")
        else:
            self.current_pos_json_path = Path(current_pos_json_path)
        if groundtrack_coverage_csv_path is None:
            self.groundtrack_coverage_csv_path = self.output_csv_path.with_name(
                f"{self.output_csv_path.stem}_groundtrack_coverage.csv"
            )
        else:
            self.groundtrack_coverage_csv_path = Path(groundtrack_coverage_csv_path)
        if elevation_states_csv_path is None:
            self.elevation_states_csv_path = self.output_csv_path.with_name(
                f"{self.output_csv_path.stem}_elevation_states.csv"
            )
        else:
            self.elevation_states_csv_path = Path(elevation_states_csv_path)
        self.node_population_ratio = max(0.0, min(1.0, float(node_population_ratio)))
        self.demd_population_ratio = max(0.0, min(1.0, float(demd_population_ratio)))
        self.minimum_frames = max(8, int(minimum_frames))
        self._simulation_start_utc = self._resolve_simulation_start_utc(simulation_start_utc)
        self._user_position_seed = int(user_position_seed)
        self._demod_activity_ratio = float(max(0.0, min(1.0, float(demod_activity_ratio))))
        self._demod_sleep_ratio = float(max(0.0, min(1.0, float(demod_sleep_ratio))))
        self._baseline_power_w = float(baseline_power_w)
        self._idle_demodulator_power_w = float(idle_demodulator_power_w)
        self._busy_demodulator_power_w = float(busy_demodulator_power_w)
        self._elev_list = self._resolve_elev_list(elev_list)
        self._elev_tokens: list[tuple[float, str]] = [
            (float(elev), self._elev_token(float(elev))) for elev in self._elev_list
        ]

        self._elev_metric_fields: list[str] = [
            "center_elevation_deg",
            "center_slant_range_km",
            "user_positions_count",
            "user_distance_min_km",
            "user_distance_max_km",
            "user_distance_mean_km",
            "elevation_impact_range_ratio",
            "elevation_impact_fspl_delta_db",
            "sample_user_positions_local_m",
        ]
        for _, token in self._elev_tokens:
            self._elev_metric_fields.append(f"elev_{token}_num_users")
            self._elev_metric_fields.append(f"elev_{token}_distance_km")
        self._csv_fieldnames = list(self.BASE_CSV_FIELDNAMES)
        self._groundtrack_coverage_fieldnames = [
            "step",
            "orbit_index",
            "sat_lat_deg",
            "sat_lon_deg",
            "footprint_radius_m",
            "footprint_area_km2",
            "footprint_earth_surface_ratio",
            "footprint_horizon_utilization_ratio",
            "covered_population_total",
            "covered_population_points",
            "covered_population_ratio",
            "covered_ocean_points",
            "covered_ocean_ratio",
            "covered_population_places",
            "covered_ocean_places",
        ]
        self._elev_states_fieldnames = ["step", "orbit_index", "orbit_timestamp_s"]
        self._elev_states_fieldnames.extend(self._elev_metric_fields)
        for _, token in self._elev_tokens:
            self._elev_states_fieldnames.append(f"elev_{token}_busy")
            self._elev_states_fieldnames.append(f"elev_{token}_idle")
            self._elev_states_fieldnames.append(f"elev_{token}_sleep")
            self._elev_states_fieldnames.append(f"elev_{token}_energy_model_w")

        self._population_points = self._load_points(self.population_csv_path)
        self._ocean_points = self._load_points(self.ocean_csv_path)
        self._total_population_catalog = int(sum(int(p["population"]) for p in self._population_points))
        self._population_catalog_points = int(len(self._population_points))
        self._ocean_catalog_points = int(len(self._ocean_points))
        self._step_count = 0
        center_lat_deg, center_lon_deg = self._resolve_rotation_center_deg()

        self._orbit_state = run_leo_orbit_rotation_task(
            params_config={
                "r_earth": float(EARTRH_R),
                "h_satellite": float(SAT_H),
                "t_frame": float(T_FRAME),
                "latitude_center": float(center_lat_deg),
                "longitude_center": float(center_lon_deg),
            },
            fallback_step_s=float(T_FRAME),
            minimum_frames=self.minimum_frames,
        )

        self._timestamps_s = np.asarray(self._orbit_state["timestamps_s"], dtype=float)
        self._sat_local = np.asarray(self._orbit_state["satellite_positions_m"], dtype=float)
        self._sat_eci = np.asarray(self._orbit_state["satellite_positions_eci_m"], dtype=float)
        self._sat_lat = np.asarray(self._orbit_state["satellite_ground_track_lat_deg"], dtype=float)
        self._sat_lon = np.asarray(self._orbit_state["satellite_ground_track_lon_deg"], dtype=float)

        self._orbit_len = int(
            min(
                self._timestamps_s.size,
                self._sat_local.shape[1],
                self._sat_eci.shape[1],
                self._sat_lat.size,
                self._sat_lon.size,
            )
        )
        if self._orbit_len <= 0:
            raise ValueError("Orbit state is empty; unable to initialize stepper.")

        self._center_index = int(np.argmin(np.abs(self._timestamps_s[: self._orbit_len])))
        self._index = int(self._center_index)
        self._index_stride = self._compute_index_stride()
        self._steps_per_orbit = int(self._orbit_len // math.gcd(self._orbit_len, self._index_stride))
        self._orbit_elapsed_lookup_s = self._build_orbit_elapsed_lookup()
        self._rows_in_cycle = 0

        self._ensure_output_header()
        self._ensure_groundtrack_coverage_header()
        self._ensure_elevation_states_header()
        self._append_current_row()  # Save original first satellite position as first row.

    @staticmethod
    def _resolve_simulation_start_utc(simulation_start_utc: datetime | str | None) -> datetime:
        if isinstance(simulation_start_utc, datetime):
            dt = simulation_start_utc
        elif isinstance(simulation_start_utc, str) and simulation_start_utc.strip():
            token = simulation_start_utc.strip()
            if token.endswith("Z"):
                token = f"{token[:-1]}+00:00"
            dt = datetime.fromisoformat(token)
        else:
            dt = datetime.now(timezone.utc)

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    @staticmethod
    def _resolve_elev_list(elev_list: list[float] | None) -> list[float]:
        if elev_list is None or len(elev_list) == 0:
            return [90.0, 55.0, 25.0]
        parsed: list[float] = []
        for e in elev_list:
            try:
                parsed.append(float(e))
            except (TypeError, ValueError):
                continue
        if len(parsed) == 0:
            return [90.0, 55.0, 22.0]
        return parsed

    def _resolve_rotation_center_deg(self) -> tuple[float, float]:
        default_lat = float(LATITUDE_CENTER_DEG)
        default_lon = float(LONGITUDE_CENTER_DEG)

        # Prefer persisted current position JSON when available.
        if self.current_pos_json_path.exists():
            try:
                with self.current_pos_json_path.open("r", encoding="utf-8") as f:
                    payload = json.load(f)
                gt = payload.get("ground_track_deg", {}) if isinstance(payload, dict) else {}
                lat = float(gt.get("latitude", default_lat))
                lon = float(gt.get("longitude", default_lon))
                return lat, lon
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                pass

        # Fallback: latest row from side CSV when available.
        if self.groundtrack_coverage_csv_path.exists():
            last_row: dict[str, str] | None = None
            try:
                with self.groundtrack_coverage_csv_path.open("r", encoding="utf-8", newline="") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        last_row = row
                if last_row is not None:
                    lat = float(last_row.get("sat_lat_deg", default_lat) or default_lat)
                    lon = float(last_row.get("sat_lon_deg", default_lon) or default_lon)
                    return lat, lon
            except (OSError, ValueError, TypeError):
                pass

        return default_lat, default_lon

    @staticmethod
    def _elev_token(elev_deg: float) -> str:
        rounded = round(float(elev_deg), 3)
        if float(rounded).is_integer():
            return f"{int(rounded)}deg"
        token = f"{rounded}".replace("-", "m").replace(".", "p")
        return f"{token}deg"

    @staticmethod
    def _load_points(csv_path: Path) -> list[dict[str, Any]]:
        if not csv_path.exists():
            raise FileNotFoundError(f"Input CSV not found: {csv_path}")

        points: list[dict[str, Any]] = []
        with csv_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    lat = float(row.get("latitude", 0.0) or 0.0)
                    lon = float(row.get("longitude", 0.0) or 0.0)
                except (TypeError, ValueError):
                    continue

                pop_raw = row.get("population", 0) or 0
                try:
                    population = max(0, int(float(pop_raw)))
                except (TypeError, ValueError):
                    population = 0

                points.append(
                    {
                        "latitude": float(lat),
                        "longitude": float(lon),
                        "population": int(population),
                        "feature_name": str(row.get("feature_name", "")).strip(),
                        "feature_type": str(row.get("feature_type", "")).strip(),
                        "country": str(row.get("country", "")).strip(),
                        "ocean": str(row.get("ocean", "")).strip(),
                    }
                )
        return points

    @staticmethod
    def _format_place_label(point: dict[str, Any]) -> str:
        name = str(point.get("feature_name", "")).strip()
        feature_type = str(point.get("feature_type", "")).strip()
        country = str(point.get("country", "")).strip()
        ocean = str(point.get("ocean", "")).strip()

        parts = [p for p in [name, feature_type, country, ocean] if p]
        if not parts:
            return "unknown"
        return "|".join(parts)

    def _compute_index_stride(self) -> int:
        if self._orbit_len < 2:
            return 1

        idx0 = self._center_index
        idx1 = (idx0 + 1) % self._orbit_len
        step_distance_m = float(np.linalg.norm(self._sat_local[:, idx1] - self._sat_local[:, idx0]))
        if step_distance_m <= 1e-9:
            return 1

        target_distance_m = float(V_SATELLITE) * float(T_FRAME)
        stride = int(round(target_distance_m / step_distance_m))
        return max(1, stride)

    def _build_orbit_elapsed_lookup(self) -> np.ndarray:
        if self._steps_per_orbit <= 0:
            return np.zeros(1, dtype=float)
        if self._orbit_len <= 1:
            return np.zeros(self._steps_per_orbit, dtype=float)

        raw_step_s = float(np.median(np.diff(self._timestamps_s[: self._orbit_len])))
        if not np.isfinite(raw_step_s) or raw_step_s <= 0.0:
            raw_step_s = float(T_FRAME)
        timeline_span_s = float(self._timestamps_s[self._orbit_len - 1] - self._timestamps_s[0] + raw_step_s)
        if timeline_span_s <= 0.0:
            timeline_span_s = float(raw_step_s * max(1, self._orbit_len))

        indices = [
            int((self._center_index + k * self._index_stride) % self._orbit_len)
            for k in range(self._steps_per_orbit)
        ]
        raw_times = [float(self._timestamps_s[idx]) for idx in indices]

        elapsed = [0.0]
        for k in range(1, len(raw_times)):
            delta_s = float(raw_times[k] - raw_times[k - 1])
            if delta_s < 0.0:
                delta_s += timeline_span_s
            elapsed.append(float(elapsed[-1] + delta_s))
        return np.asarray(elapsed, dtype=float)

    def _ensure_output_header(self) -> None:
        self.output_csv_path.parent.mkdir(parents=True, exist_ok=True)
        with self.output_csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=self._csv_fieldnames,
            )
            writer.writeheader()

    def _ensure_elevation_states_header(self) -> None:
        self.elevation_states_csv_path.parent.mkdir(parents=True, exist_ok=True)
        with self.elevation_states_csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=self._elev_states_fieldnames,
            )
            writer.writeheader()

    def _ensure_groundtrack_coverage_header(self) -> None:
        self.groundtrack_coverage_csv_path.parent.mkdir(parents=True, exist_ok=True)
        with self.groundtrack_coverage_csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=self._groundtrack_coverage_fieldnames,
            )
            writer.writeheader()

    def _save_current_pos_json(
        self,
        row: dict[str, Any],
        groundtrack_coverage_row: dict[str, Any] | None = None,
        elevation_states_row: dict[str, Any] | None = None,
    ) -> None:
        merged = dict(row)
        if groundtrack_coverage_row:
            merged.update(groundtrack_coverage_row)
        if elevation_states_row:
            merged.update(elevation_states_row)
        self.current_pos_json_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "step": int(merged["step"]),
            "orbit_index": int(merged["orbit_index"]),
            "timestamp_s": float(merged["timestamp_s"]),
            "orbit_timestamp_s": float(merged["orbit_timestamp_s"]),
            "timestamp_utc": str(merged["timestamp_utc"]),
            "position_m": {
                "x": float(merged["sat_x_m"]),
                "y": float(merged["sat_y_m"]),
                "z": float(merged["sat_z_m"]),
            },
            "sat_radius_m": float(merged["sat_radius_m"]),
            "calculated": {
                "node_population_ratio": float(merged["node_population_ratio"]),
                # "demd_population_ratio": float(merged["demd_population_ratio"]),
                "nodes": int(merged["calculated_nodes"]),
                "demodulators": float(merged["calculated_demodulators"]),
            },
        }
        if "sat_lat_deg" in merged and "sat_lon_deg" in merged:
            payload["ground_track_deg"] = {
                "latitude": float(merged["sat_lat_deg"]),
                "longitude": float(merged["sat_lon_deg"]),
            }
        if "footprint_radius_m" in merged:
            payload["footprint"] = {
                "radius_m": float(merged["footprint_radius_m"]),
                "area_km2": float(merged["footprint_area_km2"]),
                "earth_surface_ratio": float(merged["footprint_earth_surface_ratio"]),
                "horizon_utilization_ratio": float(merged["footprint_horizon_utilization_ratio"]),
            }
        if "covered_population_total" in merged:
            payload["coverage"] = {
                "population_total": int(merged["covered_population_total"]),
                "population_points": int(merged["covered_population_points"]),
                "population_ratio": float(merged["covered_population_ratio"]),
                "ocean_points": int(merged["covered_ocean_points"]),
                "ocean_ratio": float(merged["covered_ocean_ratio"]),
            }
        if "center_elevation_deg" in merged:
            payload["elevation_user_impact"] = {
                "center_elevation_deg": float(merged.get("center_elevation_deg", float("nan"))),
                "center_slant_range_km": float(merged.get("center_slant_range_km", float("nan"))),
                "user_positions_count": int(merged.get("user_positions_count", 0) or 0),
                "user_distance_min_km": float(merged.get("user_distance_min_km", float("nan"))),
                "user_distance_max_km": float(merged.get("user_distance_max_km", float("nan"))),
                "user_distance_mean_km": float(merged.get("user_distance_mean_km", float("nan"))),
                "range_ratio_vs_sat_altitude": float(merged.get("elevation_impact_range_ratio", float("nan"))),
                "fspl_delta_db_vs_zenith": float(merged.get("elevation_impact_fspl_delta_db", float("nan"))),
                "sample_user_positions_local_m": str(merged.get("sample_user_positions_local_m", "")),
            }
            payload["elevation_scenarios"] = {
                str(elev_deg): {
                    "num_users": int(merged.get(f"elev_{token}_num_users", 0) or 0),
                    "distance_km": float(merged.get(f"elev_{token}_distance_km", float("nan"))),
                    "busy_demodulators": int(merged.get(f"elev_{token}_busy", 0) or 0),
                    "idle_demodulators": int(merged.get(f"elev_{token}_idle", 0) or 0),
                    "sleep_demodulators": int(merged.get(f"elev_{token}_sleep", 0) or 0),
                    "energy_model_w": float(merged.get(f"elev_{token}_energy_model_w", float("nan"))),
                }
                for elev_deg, token in self._elev_tokens
            }
        with self.current_pos_json_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    def _write_single_latest_row(self, row: dict[str, Any]) -> None:
        self._ensure_output_header()
        with self.output_csv_path.open("a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self._csv_fieldnames)
            writer.writerow(row)

    def _write_single_latest_groundtrack_coverage_row(self, row: dict[str, Any]) -> None:
        self._ensure_groundtrack_coverage_header()
        with self.groundtrack_coverage_csv_path.open("a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self._groundtrack_coverage_fieldnames)
            writer.writerow(row)

    def _build_elevation_states_row(
        self,
        row: dict[str, Any],
        groundtrack_coverage_row: dict[str, Any],
    ) -> dict[str, Any]:
        out: dict[str, Any] = {
            "step": int(row["step"]),
            "orbit_index": int(row["orbit_index"]),
            "orbit_timestamp_s": float(row["orbit_timestamp_s"]),
        }
        user_impact = self._compute_elevation_user_impact(
            sat_x_m=float(row["sat_x_m"]),
            sat_y_m=float(row["sat_y_m"]),
            sat_z_m=float(row["sat_z_m"]),
            calculated_nodes=int(row["calculated_nodes"]),
            footprint_radius_m=float(groundtrack_coverage_row["footprint_radius_m"]),
        )
        elev_series = self._compute_elev_list_user_distances(
            calculated_nodes=int(row["calculated_nodes"]),
            footprint_radius_m=float(groundtrack_coverage_row["footprint_radius_m"]),
        )
        for k, v in user_impact.items():
            out[k] = v
        for k, v in elev_series.items():
            out[k] = v

        n_demod = int(max(0, int(row.get("calculated_demodulators", 0) or 0)))

        for _, token in self._elev_tokens:
            n_user = int(max(0, int(row.get(f"elev_{token}_num_users", 0) or 0)))
            if f"elev_{token}_num_users" in out:
                n_user = int(max(0, int(out[f"elev_{token}_num_users"] or 0)))
            n_active = int(self._demod_activity_ratio * n_user)
            n_busy = int(min(n_active, n_demod))
            remaining = int(max(0, n_demod - n_busy))
            n_sleep = int(self._demod_sleep_ratio * remaining)
            n_idle = int(remaining - n_sleep)
            energy_model_w = float(
                self._baseline_power_w
                + n_idle * self._idle_demodulator_power_w
                + n_busy * self._busy_demodulator_power_w
            )
            out[f"elev_{token}_busy"] = n_busy
            out[f"elev_{token}_idle"] = n_idle
            out[f"elev_{token}_sleep"] = n_sleep
            out[f"elev_{token}_energy_model_w"] = energy_model_w
        return out

    def _append_elevation_states_row(
        self,
        row: dict[str, Any],
        groundtrack_coverage_row: dict[str, Any],
    ) -> dict[str, Any]:
        states_row = self._build_elevation_states_row(row, groundtrack_coverage_row)
        with self.elevation_states_csv_path.open("a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self._elev_states_fieldnames)
            writer.writerow(states_row)
        return states_row

    def _write_single_latest_elevation_states_row(
        self,
        row: dict[str, Any],
        groundtrack_coverage_row: dict[str, Any],
    ) -> dict[str, Any]:
        self._ensure_elevation_states_header()
        states_row = self._build_elevation_states_row(row, groundtrack_coverage_row)
        with self.elevation_states_csv_path.open("a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self._elev_states_fieldnames)
            writer.writerow(states_row)
        return states_row

    def get_pos(self) -> dict[str, float]:
        i = self._index
        xyz = self._sat_local[:, i]
        sat_radius_m = float(np.linalg.norm(self._sat_eci[:, i]))
        cycle_step = int(self._step_count % max(1, self._steps_per_orbit))
        elapsed_s = float(self._orbit_elapsed_lookup_s[cycle_step])
        return {
            "step": float(self._step_count),
            "orbit_index": float(i),
            "timestamp_s": float(elapsed_s),
            "orbit_timestamp_s": float(elapsed_s),
            "x_m": float(xyz[0]),
            "y_m": float(xyz[1]),
            "z_m": float(xyz[2]),
            "latitude_deg": float(self._sat_lat[i]),
            "longitude_deg": float(self._sat_lon[i]),
            "sat_radius_m": sat_radius_m,
        }

    def get_footprint(self) -> dict[str, float]:
        sat_radius_m = float(np.linalg.norm(self._sat_eci[:, self._index]))
        altitude_m = float(max(0.0, sat_radius_m - float(EARTRH_R)))
        psi = compute_horizon_central_angle_rad(
            earth_radius_m=float(EARTRH_R),
            orbital_radius_m=max(sat_radius_m, float(EARTRH_R) + 1.0),
        )
        geometric_radius_m = float(EARTRH_R) * float(psi)
        # Keep footprint tied to current altitude while respecting physical horizon bound.
        if float(SAT_H) > 0.0:
            scaled_radius_m = float(R_FOOTPRINT) * (altitude_m / float(SAT_H))
        else:
            scaled_radius_m = float(R_FOOTPRINT)
        footprint_radius_m = float(max(0.0, min(geometric_radius_m, scaled_radius_m)))
        if footprint_radius_m <= 0.0:
            footprint_radius_m = float(max(0.0, min(geometric_radius_m, float(R_FOOTPRINT))))
        footprint_area_km2 = float(math.pi * footprint_radius_m * footprint_radius_m / 1_000_000.0)
        earth_surface_area_m2 = float(4.0 * math.pi * float(EARTRH_R) * float(EARTRH_R))
        footprint_earth_surface_ratio = float(
            (math.pi * footprint_radius_m * footprint_radius_m) / earth_surface_area_m2
        ) if earth_surface_area_m2 > 0.0 else 0.0
        footprint_horizon_utilization_ratio = float(
            footprint_radius_m / geometric_radius_m
        ) if geometric_radius_m > 1e-9 else 0.0
        return {
            "footprint_radius_m": float(footprint_radius_m),
            "footprint_area_km2": float(footprint_area_km2),
            "altitude_m": float(altitude_m),
            "geometric_footprint_radius_m": float(geometric_radius_m),
            "footprint_earth_surface_ratio": float(max(0.0, min(1.0, footprint_earth_surface_ratio))),
            "footprint_horizon_utilization_ratio": float(max(0.0, min(1.0, footprint_horizon_utilization_ratio))),
        }

    def _compute_coverage(self, sat_lat_deg: float, sat_lon_deg: float, footprint_radius_m: float) -> dict[str, Any]:
        covered_population_total = 0
        covered_population_points = 0
        covered_population_labels: list[str] = []
        for p in self._population_points:
            d = haversine_distance_m(
                sat_lat_deg,
                sat_lon_deg,
                float(p["latitude"]),
                float(p["longitude"]),
            )
            if d <= footprint_radius_m:
                covered_population_points += 1
                covered_population_total += int(p["population"])
                covered_population_labels.append(self._format_place_label(p))

        covered_ocean_points = 0
        covered_ocean_labels: list[str] = []
        for p in self._ocean_points:
            d = haversine_distance_m(
                sat_lat_deg,
                sat_lon_deg,
                float(p["latitude"]),
                float(p["longitude"]),
            )
            if d <= footprint_radius_m:
                covered_ocean_points += 1
                covered_ocean_labels.append(self._format_place_label(p))

        calculated_nodes = int(round(float(covered_population_total) * self.node_population_ratio))
        calculated_demodulators = int(round(float(covered_population_total) * self.demd_population_ratio))

        covered_population_ratio = float(
            covered_population_total / self._total_population_catalog
        ) if self._total_population_catalog > 0 else 0.0
        covered_ocean_ratio = float(
            covered_ocean_points / self._ocean_catalog_points
        ) if self._ocean_catalog_points > 0 else 0.0

        return {
            "covered_population_total": int(covered_population_total),
            "covered_population_points": int(covered_population_points),
            "covered_population_ratio": float(max(0.0, min(1.0, covered_population_ratio))),
            "covered_ocean_points": int(covered_ocean_points),
            "covered_ocean_ratio": float(max(0.0, min(1.0, covered_ocean_ratio))),
            "covered_population_places": ";".join(covered_population_labels),
            "covered_ocean_places": ";".join(covered_ocean_labels),
            "calculated_nodes": int(calculated_nodes),
            "calculated_demodulators": int(calculated_demodulators),
        }

    def _sample_user_positions_local(
        self,
        n_user: int,
        footprint_radius_m: float,
        rng: np.random.Generator,
    ) -> np.ndarray:
        n = int(max(0, n_user))
        if n <= 0:
            return np.zeros((3, 0), dtype=float)

        r_earth = float(EARTRH_R)
        cap_radius = float(max(0.0, footprint_radius_m))
        cos_min = float(np.cos(cap_radius / max(r_earth, 1.0)))
        theta = np.arccos(rng.uniform(cos_min, 1.0, n))
        phi = rng.uniform(0.0, 2.0 * np.pi, n)

        x = r_earth * np.sin(theta) * np.cos(phi)
        y = r_earth * np.sin(theta) * np.sin(phi)
        z = r_earth * np.cos(theta) - r_earth
        return np.vstack((x, y, z))

    def _compute_elevation_user_impact(
        self,
        sat_x_m: float,
        sat_y_m: float,
        sat_z_m: float,
        calculated_nodes: int,
        footprint_radius_m: float,
    ) -> dict[str, Any]:
        sat = np.array([float(sat_x_m), float(sat_y_m), float(sat_z_m)], dtype=float)
        center_slant_range_m = float(np.linalg.norm(sat))
        if center_slant_range_m <= 1e-12:
            center_elevation_deg = 90.0
        else:
            center_elevation_deg = float(
                np.degrees(np.arcsin(np.clip(sat[2] / center_slant_range_m, -1.0, 1.0)))
            )

        n_user = int(max(0, calculated_nodes))
        if n_user <= 0:
            return {
                "center_elevation_deg": float(center_elevation_deg),
                "center_slant_range_km": float(center_slant_range_m / 1000.0),
                "user_positions_count": 0,
                "user_distance_min_km": float("nan"),
                "user_distance_max_km": float("nan"),
                "user_distance_mean_km": float("nan"),
                "elevation_impact_range_ratio": 0.0,
                "elevation_impact_fspl_delta_db": 0.0,
                "sample_user_positions_local_m": "",
            }

        rng = np.random.default_rng(self._user_position_seed + int(self._step_count))
        users = self._sample_user_positions_local(
            n_user=n_user,
            footprint_radius_m=float(footprint_radius_m),
            rng=rng,
        )
        distances_m = np.linalg.norm(users - sat[:, None], axis=0)

        min_km = float(np.min(distances_m) / 1000.0)
        max_km = float(np.max(distances_m) / 1000.0)
        mean_km = float(np.mean(distances_m) / 1000.0)
        baseline_m = float(max(1.0, float(SAT_H)))
        mean_distance_m = float(np.mean(distances_m))
        elevation_impact_range_ratio = float(mean_distance_m / baseline_m)
        elevation_impact_fspl_delta_db = float(20.0 * np.log10(mean_distance_m / baseline_m))

        sample_count = int(min(6, n_user))
        sample_labels: list[str] = []
        for i in range(sample_count):
            sample_labels.append(f"{users[0, i]:.1f}|{users[1, i]:.1f}|{users[2, i]:.1f}")

        return {
            "center_elevation_deg": float(center_elevation_deg),
            "center_slant_range_km": float(center_slant_range_m / 1000.0),
            "user_positions_count": int(n_user),
            "user_distance_min_km": float(min_km),
            "user_distance_max_km": float(max_km),
            "user_distance_mean_km": float(mean_km),
            "elevation_impact_range_ratio": float(elevation_impact_range_ratio),
            "elevation_impact_fspl_delta_db": float(elevation_impact_fspl_delta_db),
            "sample_user_positions_local_m": ";".join(sample_labels),
        }

    def _satellite_pos_from_center_elevation(self, elev_deg: float) -> np.ndarray:
        eps = float(np.deg2rad(float(elev_deg)))
        earth_r = float(EARTRH_R)
        altitude = earth_r + float(SAT_H)
        alpha = float(np.arccos((earth_r / altitude) * np.cos(eps)) - eps)
        x_sat = altitude * np.sin(alpha)
        y_sat = 0.0
        z_sat = altitude * np.cos(alpha) - earth_r
        return np.array([x_sat, y_sat, z_sat], dtype=float)

    def _compute_elev_list_user_distances(
        self,
        calculated_nodes: int,
        footprint_radius_m: float,
    ) -> dict[str, Any]:
        n_user = int(max(0, calculated_nodes))
        output: dict[str, Any] = {}
        if n_user <= 0:
            for _, token in self._elev_tokens:
                output[f"elev_{token}_num_users"] = 0
                output[f"elev_{token}_distance_km"] = float("nan")
            return output

        rng = np.random.default_rng(self._user_position_seed + int(self._step_count))
        users = self._sample_user_positions_local(
            n_user=n_user,
            footprint_radius_m=float(footprint_radius_m),
            rng=rng,
        )

        n_bins = int(max(1, len(self._elev_tokens)))
        base = n_user // n_bins
        remainder = n_user % n_bins
        counts = [base + (1 if i < remainder else 0) for i in range(n_bins)]

        start = 0
        for i, (elev_deg, token) in enumerate(self._elev_tokens):
            count_i = int(counts[i])
            end = start + count_i
            sat = self._satellite_pos_from_center_elevation(elev_deg=elev_deg)
            output[f"elev_{token}_num_users"] = int(count_i)
            if count_i <= 0:
                output[f"elev_{token}_distance_km"] = float("nan")
            else:
                d_m = np.linalg.norm(users[:, start:end] - sat[:, None], axis=0)
                output[f"elev_{token}_distance_km"] = float(np.mean(d_m) / 1000.0)
            start = end
        return output

    def _build_current_row(self) -> tuple[dict[str, Any], dict[str, Any]]:
        pos = self.get_pos()
        footprint = self.get_footprint()
        coverage = self._compute_coverage(
            sat_lat_deg=float(pos["latitude_deg"]),
            sat_lon_deg=float(pos["longitude_deg"]),
            footprint_radius_m=float(footprint["footprint_radius_m"]),
        )
        main_row = {
            "step": int(self._step_count),
            "orbit_index": int(pos["orbit_index"]),
            "timestamp_s": float(pos["timestamp_s"]),
            "orbit_timestamp_s": float(pos["orbit_timestamp_s"]),
            "timestamp_utc": (self._simulation_start_utc + timedelta(seconds=float(pos["timestamp_s"]))).isoformat(),
            "sat_x_m": float(pos["x_m"]),
            "sat_y_m": float(pos["y_m"]),
            "sat_z_m": float(pos["z_m"]),
            "sat_radius_m": float(pos["sat_radius_m"]),
            "node_population_ratio": float(self.node_population_ratio),
            "calculated_nodes": int(coverage["calculated_nodes"]),
            "calculated_demodulators": int(coverage["calculated_demodulators"]),
        }
        groundtrack_coverage_row = {
            "step": int(self._step_count),
            "orbit_index": int(pos["orbit_index"]),
            "sat_lat_deg": float(pos["latitude_deg"]),
            "sat_lon_deg": float(pos["longitude_deg"]),
            "footprint_radius_m": float(footprint["footprint_radius_m"]),
            "footprint_area_km2": float(footprint["footprint_area_km2"]),
            "footprint_earth_surface_ratio": float(footprint["footprint_earth_surface_ratio"]),
            "footprint_horizon_utilization_ratio": float(footprint["footprint_horizon_utilization_ratio"]),
            "covered_population_total": int(coverage["covered_population_total"]),
            "covered_population_points": int(coverage["covered_population_points"]),
            "covered_population_ratio": float(coverage["covered_population_ratio"]),
            "covered_ocean_points": int(coverage["covered_ocean_points"]),
            "covered_ocean_ratio": float(coverage["covered_ocean_ratio"]),
            "covered_population_places": str(coverage["covered_population_places"]),
            "covered_ocean_places": str(coverage["covered_ocean_places"]),
        }
        return main_row, groundtrack_coverage_row

    def estimate_row_for_lat_lon(self, sat_lat_deg: float, sat_lon_deg: float) -> dict[str, Any]:
        pos = self.get_pos()
        footprint = self.get_footprint()
        coverage = self._compute_coverage(
            sat_lat_deg=float(sat_lat_deg),
            sat_lon_deg=float(sat_lon_deg),
            footprint_radius_m=float(footprint["footprint_radius_m"]),
        )
        return {
            "step": int(self._step_count),
            "orbit_index": int(pos["orbit_index"]),
            "timestamp_s": float(pos["timestamp_s"]),
            "orbit_timestamp_s": float(pos["orbit_timestamp_s"]),
            "timestamp_utc": (self._simulation_start_utc + timedelta(seconds=float(pos["timestamp_s"]))).isoformat(),
            "sat_x_m": float(pos["x_m"]),
            "sat_y_m": float(pos["y_m"]),
            "sat_z_m": float(pos["z_m"]),
            "node_population_ratio": float(self.node_population_ratio),
            "sat_lat_deg": float(sat_lat_deg),
            "sat_lon_deg": float(sat_lon_deg),
            "sat_radius_m": float(pos["sat_radius_m"]),
            "footprint_radius_m": float(footprint["footprint_radius_m"]),
            "footprint_area_km2": float(footprint["footprint_area_km2"]),
            "footprint_earth_surface_ratio": float(footprint["footprint_earth_surface_ratio"]),
            "footprint_horizon_utilization_ratio": float(footprint["footprint_horizon_utilization_ratio"]),
            "covered_population_total": int(coverage["covered_population_total"]),
            "covered_population_points": int(coverage["covered_population_points"]),
            "covered_population_ratio": float(coverage["covered_population_ratio"]),
            "covered_ocean_points": int(coverage["covered_ocean_points"]),
            "covered_ocean_ratio": float(coverage["covered_ocean_ratio"]),
            "covered_population_places": str(coverage["covered_population_places"]),
            "covered_ocean_places": str(coverage["covered_ocean_places"]),
            "calculated_nodes": int(coverage["calculated_nodes"]),
            "calculated_demodulators": int(coverage["calculated_demodulators"]),
        }

    def get_nodes_demods_for_lat_lon(self, sat_lat_deg: float, sat_lon_deg: float) -> tuple[int, int]:
        row = self.estimate_row_for_lat_lon(sat_lat_deg=sat_lat_deg, sat_lon_deg=sat_lon_deg)
        return int(row["calculated_nodes"]), int(row["calculated_demodulators"])

    def _read_latest_csv_row(self) -> dict[str, str] | None:
        if not self.output_csv_path.exists():
            return None
        last_row: dict[str, str] | None = None
        with self.output_csv_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                last_row = row
        return last_row

    def get_current_nodes(self) -> int:
        row = self._read_latest_csv_row()
        if row is None:
            return 0
        try:
            return int(float(row.get("calculated_nodes", 0) or 0))
        except (TypeError, ValueError):
            return 0

    def get_current_demodulators(self) -> int:
        row = self._read_latest_csv_row()
        if row is None:
            return 0
        try:
            return int(float(row.get("calculated_demodulators", 0) or 0))
        except (TypeError, ValueError):
            return 0

    def _load_sorted_elevation_state_rows(self) -> list[dict[str, str]]:
        if not self.elevation_states_csv_path.exists():
            return []

        rows: list[dict[str, str]] = []
        with self.elevation_states_csv_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
        if not rows:
            return []

        rows.sort(
            key=lambda row: (
                float(row.get("orbit_timestamp_s", 0.0) or 0.0),
                int(float(row.get("step", 0) or 0)),
            )
        )
        return rows

    def plot_elevation_energy_timeseries(self, output_dir: str | Path | None = None) -> list[Path]:
        if plt is None:
            return []

        if output_dir is None:
            plots_dir = self.elevation_states_csv_path.parent / "plots"
        else:
            plots_dir = Path(output_dir)
        plots_dir.mkdir(parents=True, exist_ok=True)

        rows = self._load_sorted_elevation_state_rows()
        if not rows:
            return []

        plot_paths: list[Path] = []
        for elev_deg, token in self._elev_tokens:
            energy_field = f"elev_{token}_energy_model_w"
            if energy_field not in rows[0]:
                continue

            orbit_timestamp_s = [float(row.get("orbit_timestamp_s", 0.0) or 0.0) for row in rows]
            energy_model_w = [float(row.get(energy_field, 0.0) or 0.0) for row in rows]

            fig, ax = plt.subplots(figsize=(10, 5))
            ax.plot(orbit_timestamp_s, energy_model_w, color="#c0392b", linewidth=2.0)
            ax.set_title(f"Orbit Timestamp vs Energy Model @ {elev_deg:g} deg")
            ax.set_xlabel("orbit_timestamp_s")
            ax.set_ylabel("energy_model_w")
            ax.grid(True, linestyle="-", linewidth=0.5, alpha=0.35)
            fig.tight_layout()

            out_path = plots_dir / f"satellite_stepper_energy_{token}.png"
            fig.savefig(out_path, dpi=220)
            plt.close(fig)
            plot_paths.append(out_path)

        return plot_paths

    def plot_combined_elevation_energy_timeseries(
        self,
        output_dir: str | Path | None = None,
    ) -> Path | None:
        if plt is None:
            return None

        if output_dir is None:
            plots_dir = self.elevation_states_csv_path.parent / "plots"
        else:
            plots_dir = Path(output_dir)
        plots_dir.mkdir(parents=True, exist_ok=True)

        rows = self._load_sorted_elevation_state_rows()
        if not rows:
            return None

        orbit_timestamp_s = [float(row.get("orbit_timestamp_s", 0.0) or 0.0) for row in rows]
        color_map = plt.get_cmap("tab10")

        fig, ax = plt.subplots(figsize=(11, 6))
        plotted = False
        for idx, (elev_deg, token) in enumerate(self._elev_tokens):
            energy_field = f"elev_{token}_energy_model_w"
            if energy_field not in rows[0]:
                continue

            energy_model_w = [float(row.get(energy_field, 0.0) or 0.0) for row in rows]
            ax.plot(
                orbit_timestamp_s,
                energy_model_w,
                linewidth=2.0,
                color=color_map(idx % 10),
                label=f"{elev_deg:g} deg",
            )
            plotted = True

        if not plotted:
            plt.close(fig)
            return None

        ax.set_title("Orbit Timestamp vs Energy Model for All Elevations")
        ax.set_xlabel("orbit_timestamp_s")
        ax.set_ylabel("energy_model_w")
        ax.grid(True, linestyle="-", linewidth=0.5, alpha=0.35)
        ax.legend(title="Elevation")
        fig.tight_layout()

        out_path = plots_dir / "satellite_stepper_energy_all_elevations.png"
        fig.savefig(out_path, dpi=220)
        plt.close(fig)
        return out_path

    def _append_current_row(self) -> dict[str, Any]:
        row, groundtrack_coverage_row = self._build_current_row()
        with self.output_csv_path.open("a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self._csv_fieldnames)
            writer.writerow(row)
        with self.groundtrack_coverage_csv_path.open("a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self._groundtrack_coverage_fieldnames)
            writer.writerow(groundtrack_coverage_row)
        elevation_states_row = self._append_elevation_states_row(row, groundtrack_coverage_row)
        self._rows_in_cycle += 1
        self._save_current_pos_json(row, groundtrack_coverage_row, elevation_states_row)
        return row
    
    def current(self) -> dict[str, Any]:
        row, groundtrack_coverage_row = self._build_current_row()
        elevation_states_row = self._build_elevation_states_row(row, groundtrack_coverage_row)
        self._save_current_pos_json(row, groundtrack_coverage_row, elevation_states_row)
        return row

    def next(self) -> dict[str, Any]:
        self._index = int((self._index + self._index_stride) % self._orbit_len)
        self._step_count += 1
        row, groundtrack_coverage_row = self._build_current_row()

        # Once one-orbit capacity is reached, clear CSV rows and keep only latest row.
        if self._rows_in_cycle + 1 >= self._steps_per_orbit:
            self._write_single_latest_row(row)
            self._write_single_latest_groundtrack_coverage_row(groundtrack_coverage_row)
            elevation_states_row = self._write_single_latest_elevation_states_row(row, groundtrack_coverage_row)
            self._rows_in_cycle = 1
            self._save_current_pos_json(row, groundtrack_coverage_row, elevation_states_row)
            return row

        with self.output_csv_path.open("a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self._csv_fieldnames)
            writer.writerow(row)
        with self.groundtrack_coverage_csv_path.open("a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self._groundtrack_coverage_fieldnames)
            writer.writerow(groundtrack_coverage_row)
        elevation_states_row = self._append_elevation_states_row(row, groundtrack_coverage_row)
        self._rows_in_cycle += 1
        self._save_current_pos_json(row, groundtrack_coverage_row, elevation_states_row)
        return row


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Kepler-aligned satellite stepper and append step-wise coverage rows to CSV.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("results/one_pos_satellite/satellite_steps.csv"),
        help="Output CSV file path.",
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=1,
        help="Number of next() steps to execute after initial row is written.",
    )
    parser.add_argument(
        "--population-csv",
        type=Path,
        default=Path("Data/csv/population_data.csv"),
        help="Population CSV path.",
    )
    parser.add_argument(
        "--ocean-csv",
        type=Path,
        default=Path("Data/csv/ocean_data.csv"),
        help="Ocean CSV path.",
    )
    parser.add_argument(
        "--current-pos-json",
        type=Path,
        default=None,
        help="Current-position JSON file path (default: beside output CSV).",
    )
    parser.add_argument(
        "--groundtrack-coverage-csv",
        type=Path,
        default=None,
        help="Optional CSV path for ground-track, footprint, and coverage columns.",
    )
    parser.add_argument(
        "--elevation-states-csv",
        type=Path,
        default=None,
        help="Optional CSV path for per-elevation demod states (busy/idle/sleep).",
    )
    parser.add_argument(
        "--node-population-ratio",
        type=float,
        default=node_population_ratio,
        help="Estimated node ratio from covered population.",
    )
    parser.add_argument(
        "--demd_population_ratio",
        type=float,
        default=demd_population_ratio,
        help="demodulator population ratio",
    )
    parser.add_argument(
        "--minimum-frames",
        type=int,
        default=720,
        help="Minimum Kepler orbit frames used by the stepper.",
    )
    parser.add_argument(
        "--simulation-start-utc",
        type=str,
        default=None,
        help="Simulation start time in ISO-8601 UTC format (e.g. 2026-04-18T00:00:00Z).",
    )
    parser.add_argument(
        "--user-position-seed",
        type=int,
        default=42,
        help="Base seed for per-step user position sampling used in elevation impact metrics.",
    )
    parser.add_argument(
        "--elev-list",
        type=float,
        nargs="+",
        default=[90.0, 55.0, 25.0],
        help="Elevation scenarios (deg) used for per-step user-distance columns.",
    )
    parser.add_argument("--demod-activity-ratio", type=float, default=0.1)
    parser.add_argument("--demod-sleep-ratio", type=float, default=0.3)
    parser.add_argument("--baseline-power-w", type=float, default=35.0)
    parser.add_argument("--idle-demodulator-power-w", type=float, default=0.12)
    parser.add_argument("--busy-demodulator-power-w", type=float, default=0.80)
    return parser


def main() -> int:
    parser = _build_arg_parser()
    args = parser.parse_args()

    steps = max(0, int(args.steps))
    stepper = SatelliteStepper(
        output_csv_path=args.output,
        population_csv_path=args.population_csv,
        ocean_csv_path=args.ocean_csv,
        current_pos_json_path=args.current_pos_json,
        groundtrack_coverage_csv_path=args.groundtrack_coverage_csv,
        elevation_states_csv_path=args.elevation_states_csv,
        node_population_ratio=float(args.node_population_ratio),
        demd_population_ratio=float(args.demd_population_ratio),
        minimum_frames=int(args.minimum_frames),
        simulation_start_utc=args.simulation_start_utc,
        user_position_seed=int(args.user_position_seed),
        elev_list=[float(v) for v in args.elev_list],
        demod_activity_ratio=float(args.demod_activity_ratio),
        demod_sleep_ratio=float(args.demod_sleep_ratio),
        baseline_power_w=float(args.baseline_power_w),
        idle_demodulator_power_w=float(args.idle_demodulator_power_w),
        busy_demodulator_power_w=float(args.busy_demodulator_power_w),
    )
    last_row = None
    for _ in range(steps):
        last_row = stepper.next()

    plot_paths = stepper.plot_elevation_energy_timeseries()
    combined_plot_path = stepper.plot_combined_elevation_energy_timeseries()

    if last_row is None:
        pos = stepper.get_pos()
        footprint = stepper.get_footprint()
        print(
            f"initialized_only output={args.output} step={int(pos['step'])} "
            f"lat={float(pos['latitude_deg']):.6f} lon={float(pos['longitude_deg']):.6f} "
            f"footprint_m={float(footprint['footprint_radius_m']):.3f}"
        )
    else:
        print(
            f"completed output={args.output} rows_added={steps + 1} "
            f"last_step={int(last_row['step'])} "
            f"nodes={int(last_row['calculated_nodes'])} "
            f"demods={int(last_row['calculated_demodulators'])} "
            f"current_json={stepper.current_pos_json_path}"
        )
    if plot_paths:
        print("energy_plots=" + ",".join(str(path) for path in plot_paths))
    elif plt is None:
        print("energy_plots=skipped_matplotlib_not_installed")
    if combined_plot_path is not None:
        print(f"energy_plot_combined={combined_plot_path}")
    elif plt is None:
        print("energy_plot_combined=skipped_matplotlib_not_installed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
