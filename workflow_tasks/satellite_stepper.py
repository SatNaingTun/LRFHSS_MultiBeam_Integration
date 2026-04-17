from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import sys
from typing import Any

import numpy as np

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
)


class SatelliteKeplerStepper:
    """
    Step-wise satellite tracker with Kepler-aligned orbit propagation.

    - get_pos(): current satellite position/state
    - get_footprint(): footprint radius derived from current satellite position
    - next(): advance one logical step and append one CSV row
    """
    CSV_FIELDNAMES = [
        "step",
        "orbit_index",
        "timestamp_s",
        "sat_x_m",
        "sat_y_m",
        "sat_z_m",
        "sat_lat_deg",
        "sat_lon_deg",
        "sat_radius_m",
        "footprint_radius_m",
        "footprint_area_km2",
        "covered_population_total",
        "covered_population_points",
        "covered_ocean_points",
        "covered_population_places",
        "covered_ocean_places",
        "calculated_nodes",
        "calculated_demodulators",
    ]

    def __init__(
        self,
        output_csv_path: str | Path,
        population_csv_path: str | Path = "Data/csv/population_data.csv",
        ocean_csv_path: str | Path = "Data/csv/ocean_data.csv",
        current_pos_json_path: str | Path | None = None,
        node_penetration_ratio: float = 0.001,
        nodes_per_demodulator: int = 250,
        minimum_frames: int = 720,
    ) -> None:
        self.output_csv_path = Path(output_csv_path)
        self.population_csv_path = Path(population_csv_path)
        self.ocean_csv_path = Path(ocean_csv_path)
        if current_pos_json_path is None:
            self.current_pos_json_path = self.output_csv_path.with_name(f"{self.output_csv_path.stem}_current_pos.json")
        else:
            self.current_pos_json_path = Path(current_pos_json_path)
        self.node_penetration_ratio = max(0.0, min(1.0, float(node_penetration_ratio)))
        self.nodes_per_demodulator = max(1, int(nodes_per_demodulator))
        self.minimum_frames = max(8, int(minimum_frames))

        self._population_points = self._load_points(self.population_csv_path)
        self._ocean_points = self._load_points(self.ocean_csv_path)
        self._step_count = 0

        self._orbit_state = run_leo_orbit_rotation_task(
            params_config={
                "r_earth": float(EARTRH_R),
                "h_satellite": float(SAT_H),
                "t_frame": float(T_FRAME),
                "latitude_center": float(LATITUDE_CENTER_DEG),
                "longitude_center": float(LONGITUDE_CENTER_DEG),
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
        self._rows_in_cycle = 0

        self._ensure_output_header()
        self._append_current_row()  # Save original first satellite position as first row.

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

    def _ensure_output_header(self) -> None:
        self.output_csv_path.parent.mkdir(parents=True, exist_ok=True)
        with self.output_csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=self.CSV_FIELDNAMES,
            )
            writer.writeheader()

    def _save_current_pos_json(self, row: dict[str, Any]) -> None:
        self.current_pos_json_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "step": int(row["step"]),
            "orbit_index": int(row["orbit_index"]),
            "timestamp_s": float(row["timestamp_s"]),
            "position_m": {
                "x": float(row["sat_x_m"]),
                "y": float(row["sat_y_m"]),
                "z": float(row["sat_z_m"]),
            },
            "ground_track_deg": {
                "latitude": float(row["sat_lat_deg"]),
                "longitude": float(row["sat_lon_deg"]),
            },
            "sat_radius_m": float(row["sat_radius_m"]),
            "footprint": {
                "radius_m": float(row["footprint_radius_m"]),
                "area_km2": float(row["footprint_area_km2"]),
            },
            "coverage": {
                "population_total": int(row["covered_population_total"]),
                "population_points": int(row["covered_population_points"]),
                "ocean_points": int(row["covered_ocean_points"]),
            },
            "calculated": {
                "nodes": int(row["calculated_nodes"]),
                "demodulators": int(row["calculated_demodulators"]),
            },
        }
        with self.current_pos_json_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    def _write_single_latest_row(self, row: dict[str, Any]) -> None:
        self._ensure_output_header()
        with self.output_csv_path.open("a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self.CSV_FIELDNAMES)
            writer.writerow(row)

    def get_pos(self) -> dict[str, float]:
        i = self._index
        xyz = self._sat_local[:, i]
        sat_radius_m = float(np.linalg.norm(self._sat_eci[:, i]))
        return {
            "step": float(self._step_count),
            "orbit_index": float(i),
            "timestamp_s": float(self._timestamps_s[i]),
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
        return {
            "footprint_radius_m": float(footprint_radius_m),
            "footprint_area_km2": float(footprint_area_km2),
            "altitude_m": float(altitude_m),
            "geometric_footprint_radius_m": float(geometric_radius_m),
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

        calculated_nodes = int(round(float(covered_population_total) * self.node_penetration_ratio))
        calculated_demodulators = int(math.ceil(calculated_nodes / self.nodes_per_demodulator)) if calculated_nodes > 0 else 0

        return {
            "covered_population_total": int(covered_population_total),
            "covered_population_points": int(covered_population_points),
            "covered_ocean_points": int(covered_ocean_points),
            "covered_population_places": ";".join(covered_population_labels),
            "covered_ocean_places": ";".join(covered_ocean_labels),
            "calculated_nodes": int(calculated_nodes),
            "calculated_demodulators": int(calculated_demodulators),
        }

    def _build_current_row(self) -> dict[str, Any]:
        pos = self.get_pos()
        footprint = self.get_footprint()
        coverage = self._compute_coverage(
            sat_lat_deg=float(pos["latitude_deg"]),
            sat_lon_deg=float(pos["longitude_deg"]),
            footprint_radius_m=float(footprint["footprint_radius_m"]),
        )
        return {
            "step": int(self._step_count),
            "orbit_index": int(pos["orbit_index"]),
            "timestamp_s": float(pos["timestamp_s"]),
            "sat_x_m": float(pos["x_m"]),
            "sat_y_m": float(pos["y_m"]),
            "sat_z_m": float(pos["z_m"]),
            "sat_lat_deg": float(pos["latitude_deg"]),
            "sat_lon_deg": float(pos["longitude_deg"]),
            "sat_radius_m": float(pos["sat_radius_m"]),
            "footprint_radius_m": float(footprint["footprint_radius_m"]),
            "footprint_area_km2": float(footprint["footprint_area_km2"]),
            "covered_population_total": int(coverage["covered_population_total"]),
            "covered_population_points": int(coverage["covered_population_points"]),
            "covered_ocean_points": int(coverage["covered_ocean_points"]),
            "covered_population_places": str(coverage["covered_population_places"]),
            "covered_ocean_places": str(coverage["covered_ocean_places"]),
            "calculated_nodes": int(coverage["calculated_nodes"]),
            "calculated_demodulators": int(coverage["calculated_demodulators"]),
        }

    def _append_current_row(self) -> dict[str, Any]:
        row = self._build_current_row()
        with self.output_csv_path.open("a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self.CSV_FIELDNAMES)
            writer.writerow(row)
        self._rows_in_cycle += 1
        self._save_current_pos_json(row)
        return row

    def next(self) -> dict[str, Any]:
        self._index = int((self._index + self._index_stride) % self._orbit_len)
        self._step_count += 1
        row = self._build_current_row()

        # Once one-orbit capacity is reached, clear CSV rows and keep only latest row.
        if self._rows_in_cycle + 1 >= self._steps_per_orbit:
            self._write_single_latest_row(row)
            self._rows_in_cycle = 1
            self._save_current_pos_json(row)
            return row

        with self.output_csv_path.open("a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self.CSV_FIELDNAMES)
            writer.writerow(row)
        self._rows_in_cycle += 1
        self._save_current_pos_json(row)
        return row


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Kepler-aligned satellite stepper and append step-wise coverage rows to CSV.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("results/satellite_stepper/satellite_steps.csv"),
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
        "--node-penetration-ratio",
        type=float,
        default=0.001,
        help="Estimated node ratio from covered population.",
    )
    parser.add_argument(
        "--nodes-per-demodulator",
        type=int,
        default=250,
        help="Node capacity per demodulator.",
    )
    parser.add_argument(
        "--minimum-frames",
        type=int,
        default=720,
        help="Minimum Kepler orbit frames used by the stepper.",
    )
    return parser


def main() -> int:
    parser = _build_arg_parser()
    args = parser.parse_args()

    steps = max(0, int(args.steps))
    stepper = SatelliteKeplerStepper(
        output_csv_path=args.output,
        population_csv_path=args.population_csv,
        ocean_csv_path=args.ocean_csv,
        current_pos_json_path=args.current_pos_json,
        node_penetration_ratio=float(args.node_penetration_ratio),
        nodes_per_demodulator=int(args.nodes_per_demodulator),
        minimum_frames=int(args.minimum_frames),
    )
    last_row = None
    for _ in range(steps):
        last_row = stepper.next()

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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
