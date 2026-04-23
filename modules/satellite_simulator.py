from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path
import sys
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from matplotlib import pyplot as plt
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    plt = None

try:
    from tqdm import tqdm
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    def tqdm(iterable, desc: str | None = None):
        return iterable
    


from ProjectConfig import demd_population_ratio, elev_list, node_population_ratio
from modules.demodulator_allocator import RecursiveReuseDemodAllocator
from modules.satellite_stepper import SatelliteStepper


class SatelliteSimulator:
    """
    Satellite simulation helper with paper-inspired demodulator allocation.

    Demod flow:
    - Uses RecursiveReuseDemodAllocator (FIFO-RR inspired) as the allocation core.
    - Keeps power states (idle/sleep) for reporting/plot labels.
    """

    __slots__ = (
        "_satellite_stepper",
        "_existing_demods",
        "_all_projectory_demod_allocator",
        "_elev_demod_allocator",
        "_busy_hold_steps",
        "_sim_module",
    )

    def __init__(
        self,
        existing_demods: int | None = None,
        satellite_stepper: SatelliteStepper | None = None,
        step: int | None = None,
        busy_hold_steps: int = 1,
        idle_to_sleep_steps: int = 2,
    ) -> None:
        self._satellite_stepper = satellite_stepper or self._build_default_stepper()
        self._busy_hold_steps = max(1, int(busy_hold_steps))

        if existing_demods is None:
            self._existing_demods = self._resolve_existing_demods_from_stepper(step=step)
        else:
            self._existing_demods = self._validate_non_negative_int(existing_demods, "existing_demods")

        self._all_projectory_demod_allocator = RecursiveReuseDemodAllocator(
            num_demods=int(self._existing_demods),
            idle_to_sleep_ticks=max(0, int(idle_to_sleep_steps)),
            default_payload_ticks=max(1, int(self._busy_hold_steps)),
        )
        self._elev_demod_allocator = RecursiveReuseDemodAllocator(
            num_demods=int(self._existing_demods),
            idle_to_sleep_ticks=max(0, int(idle_to_sleep_steps)),
            default_payload_ticks=max(1, int(self._busy_hold_steps)),
        )
        
        self._sim_module = None

    @staticmethod
    def _validate_non_negative_int(value: int, field_name: str) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name} must be an integer.") from exc
        if parsed < 0:
            raise ValueError(f"{field_name} must be >= 0.")
        return parsed

    def _build_default_stepper(self) -> SatelliteStepper:
        root = Path(__file__).resolve().parents[1]
        output_csv = root / "results" / "multi_step_lrfhss" / "satellite_steps.csv"
        current_json = root / "results" / "multi_step_lrfhss" / "satellite_steps_current_pos.json"
        return SatelliteStepper(
            output_csv_path=output_csv,
            current_pos_json_path=current_json,
            node_population_ratio=float(node_population_ratio),
            demd_population_ratio=float(demd_population_ratio),
            minimum_frames=720,
        )

    def _resolve_existing_demods_from_stepper(self, step: int | None) -> int:
        if step is None:
            try:
                current_pos = self._satellite_stepper.get_pos()
                target_step = int(float(current_pos.get("step", 0) or 0))
            except (AttributeError, TypeError, ValueError):
                target_step = 0
        else:
            target_step = int(step)

        mean_demods = float(self._satellite_stepper.get_mean_demodulators(target_step))
        return max(0, int(math.ceil(mean_demods)))

    @property
    def satellite_stepper(self) -> SatelliteStepper:
        return self._satellite_stepper

    @property
    def existing_demods(self) -> int:
        return self._existing_demods

    @property
    def idle_demods(self) -> int:
        snap = self._elev_demod_allocator.snapshot()
        return int(snap.idle)

    @property
    def busy_demods(self) -> int:
        snap = self._elev_demod_allocator.snapshot()
        return int(snap.busy + snap.booked)

    @property
    def sleep_demods(self) -> int:
        snap = self._elev_demod_allocator.snapshot()
        return int(snap.sleep)

    def _demod_info(self) -> dict[str, int]:
        snap = self._elev_demod_allocator.snapshot()
        return {
            "busy": int(snap.busy + snap.booked),
            "idle": int(snap.idle),
            "sleep": int(snap.sleep),
            "booked": int(snap.booked),
        }

    def _get_lrfhss_sim_module(self):
        if self._sim_module is not None:
            return self._sim_module
        try:
            from LRFHSS import LRFHSS_simulator as lrfhss_sim_module
        except ModuleNotFoundError as exc:
            raise ModuleNotFoundError(
                "LR-FHSS simulator dependencies are missing. Install required packages "
                "(for example, `galois`) to run run_lrfhss_simulator_one_step."
            ) from exc
        self._sim_module = lrfhss_sim_module
        return self._sim_module

    def run_lrfhss_simulator_one_step(self, args: Any, one_pos_output_dir: Path) -> dict[str, Any]:
        stepper = self._satellite_stepper
        stepper.next()
        self._all_projectory_demod_allocator.advance_tick(1)
        self._elev_demod_allocator.advance_tick(1)

        current_pos = stepper.get_pos()
        sat_lat = float(current_pos["latitude_deg"] if getattr(args, "sat_lat", None) is None else args.sat_lat)
        sat_lon = float(current_pos["longitude_deg"] if getattr(args, "sat_lon", None) is None else args.sat_lon)

        if getattr(args, "sat_lat", None) is not None or getattr(args, "sat_lon", None) is not None:
            est_row = stepper.estimate_row_for_lat_lon(sat_lat_deg=sat_lat, sat_lon_deg=sat_lon)
            step_row = est_row
        else:
            cur_row = stepper.current()
            step_row = cur_row

        drop_mode_raw = str(getattr(args, "drop_mode", "rlydd"))
        drop_mode = "hdrdd" if drop_mode_raw == "headerdrop" else drop_mode_raw

        requested_nodes = int(step_row.get("calculated_nodes", 0) or 0)
        requested_demods = max(1, int(step_row.get("calculated_demodulators", 0) or 0))
        demod_activity_ratio = float(max(0.0, getattr(stepper, "_demod_activity_ratio", 0.1)))

        lrfhss_root = Path(getattr(args, "lrfhss_root", Path(__file__).resolve().parents[1] / "LRFHSS")).resolve()
        if str(lrfhss_root) not in sys.path:
            sys.path.insert(0, str(lrfhss_root))

        one_pos_output_dir.mkdir(parents=True, exist_ok=True)
        
        preloop_requested_use = max(
            1,
            int(round(float(max(1, requested_nodes)) * demod_activity_ratio)),
        )
        preloop_payload_ticks = max(1, int(self._busy_hold_steps))
        preloop_preamble_ticks = max(1, int(round(preloop_payload_ticks / 3.0)))
        preloop_snap = self._all_projectory_demod_allocator.allocate(
            requested_frames=preloop_requested_use,
            preamble_ticks=preloop_preamble_ticks,
            payload_ticks=preloop_payload_ticks,
            max_frame_ticks=int(preloop_preamble_ticks + preloop_payload_ticks),
        )
        num_decoders = max(1, int(preloop_snap.engaged))
        preloop_demod_info = {
            "busy": int(preloop_snap.busy + preloop_snap.booked),
            "idle": int(preloop_snap.idle),
            "sleep": int(preloop_snap.sleep),
            "booked": int(preloop_snap.booked),
        }

        out_csv = (
            one_pos_output_dir
            / str(int(step_row.get("orbit_index", current_pos.get("orbit_index", 0)) or 0))
            / "all"
            / f"lrfhss_sim_cr{int(args.coding_rate)}_one_pos.csv"
        )
        out_png = (
            one_pos_output_dir
            / str(int(step_row.get("orbit_index", current_pos.get("orbit_index", 0)) or 0))
            / "all"
            / f"lrfhss_demod_{int(num_decoders)}.png"
        )
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        out_png.parent.mkdir(parents=True, exist_ok=True)
        self._get_lrfhss_sim_module().runsim2plot(
            num_decoders=int(num_decoders),
            drop_mode=str(drop_mode),
            filename=out_csv,
            coding_rate=int(args.coding_rate),
            metric=str(args.metric),
            include_lifan=bool(args.include_lifan),
            include_infp=bool(args.include_infp),
            inf_demods=args.inf_demods,
            node_min=args.node_min,
            node_max=args.node_max,
            # selected_nodes=selected_nodes,
            node_points=int(requested_nodes),
            runs_per_node=max(1, int(args.runs_per_node)),
            link_budget_log=bool(args.link_budget_log),
            plot_enabled=bool(args.plot_enabled),
            plot_filename=out_png,
            x_min=args.x_min,
            x_max=args.x_max,
            y_min=args.y_min,
            y_max=args.y_max,
            title=(
                f"Step {int(step_row.get('step', current_pos.get('step', 0)) or 0)} | "
                # f"Orbit {int(step_row.get('orbit_index', current_pos.get('orbit_index', 0)) or 0)} | "
                # f"t={float(step_row.get('timestamp_s', current_pos.get('timestamp_s', 0.0)) or 0.0):.1f}s\n"
                f"ALL | CR{int(args.coding_rate)} | mode={str(drop_mode)} | metric={str(args.metric)} | "
                f"decoders={int(num_decoders)} | nodes={int(requested_nodes)}\n"
                f"demods busy={int(preloop_demod_info['busy'])}, booked={int(preloop_demod_info['booked'])}, "
                f"idle={int(preloop_demod_info['idle'])}, sleep={int(preloop_demod_info['sleep'])}"
            ),
        )
        include_elev = bool(getattr(args, "include_elev", True))
        if include_elev:
            elevations = getattr(args, "elev_list", elev_list)
            if elevations is None:
                elevations = elev_list

            pbar = tqdm(elevations, desc="Processing Elevations")
            for elev in pbar:
                stepper_demod_info = stepper.get_current_demodulators_for_elevation(elev)
                node_info = stepper.get_current_nodes_for_elevation(elev)

                requested_use = max(1, int(stepper_demod_info.get("busy", 0) or 0))
                requested_nodes = int(node_info.get("num_nodes", 0) or 0)
                distance_km = float(node_info.get("distance_km", float("nan")))

                # Lower elevation (larger slant range) maps to longer payload occupancy.
                payload_ticks = max(1, int(round(self._busy_hold_steps * (1.0 if not math.isfinite(distance_km) else max(1.0, distance_km / 600.0)))))
                preamble_ticks = max(1, int(round(payload_ticks / 3.0)))
                max_frame_ticks = int(preamble_ticks + payload_ticks)

                snap = self._elev_demod_allocator.allocate(
                    requested_frames=requested_use,
                    preamble_ticks=preamble_ticks,
                    payload_ticks=payload_ticks,
                    max_frame_ticks=max_frame_ticks,
                )
                num_decoders = max(1, int(snap.engaged))
                demod_info = self._demod_info()

                elev_out_csv = (
                    one_pos_output_dir
                    / str(int(step_row.get("orbit_index", current_pos.get("orbit_index", 0)) or 0))
                    / str(int(elev))
                    / f"lrfhss_sim_cr{int(getattr(args, 'coding_rate', 1))}_elev{int(elev)}.csv"
                )
                elev_out_png = (
                    one_pos_output_dir
                    / str(int(step_row.get("orbit_index", current_pos.get("orbit_index", 0)) or 0))
                    / str(int(elev))
                    / f"lrfhss_demod_{int(num_decoders)}_elev{int(elev)}.png"
                )
                elev_out_csv.parent.mkdir(parents=True, exist_ok=True)
                elev_out_png.parent.mkdir(parents=True, exist_ok=True)
                self._get_lrfhss_sim_module().runsim2plot(
                    num_decoders=int(num_decoders),
                    drop_mode=str(drop_mode),
                    filename=elev_out_csv,
                    coding_rate=int(getattr(args, "coding_rate", 1)),
                    metric=str(getattr(args, "metric", "dec_payld")),
                    include_lifan=bool(getattr(args, "include_lifan", False)),
                    include_infp=bool(getattr(args, "include_infp", False)),
                    inf_demods=getattr(args, "inf_demods", None),
                    node_min=getattr(args, "node_min", None),
                    node_max=getattr(args, "node_max", 10000.0),
                    node_points=int(requested_nodes),
                    runs_per_node=max(1, int(getattr(args, "runs_per_node", 1))),
                    link_budget_log=bool(getattr(args, "link_budget_log", True)),
                    plot_enabled=bool(getattr(args, "plot_enabled", True)),
                    plot_filename=elev_out_png,
                    x_min=getattr(args, "x_min", 100),
                    x_max=getattr(args, "x_max", 10000.0),
                    y_min=getattr(args, "y_min", None),
                    y_max=getattr(args, "y_max", 2600),
                    title=(
                        f"Step {int(step_row.get('step', current_pos.get('step', 0)) or 0)} | "
                        f"Elev {int(elev)}deg | CR{int(getattr(args, 'coding_rate', 1))} | mode={str(drop_mode)} | "
                        f"metric={str(getattr(args, 'metric', 'dec_payld'))} | decoders={int(num_decoders)} | "
                        f"nodes={int(requested_nodes)} | dist={float(distance_km):.1f} km\n"
                        f"demods busy={int(demod_info['busy'])}, booked={int(demod_info['booked'])}, "
                        f"idle={int(demod_info['idle'])}, sleep={int(demod_info['sleep'])}"
                    ),
                    fixed_elevation=int(elev),
                )

        return {
            "step": int(step_row.get("step", current_pos.get("step", 0)) or 0),
            "orbit_index": int(step_row.get("orbit_index", current_pos.get("orbit_index", 0)) or 0),
            "timestamp_s": float(step_row.get("timestamp_s", current_pos.get("timestamp_s", 0.0)) or 0.0),
            "timestamp_utc": str(step_row.get("timestamp_utc", "")),
        }

    @staticmethod
    def append_one_pos_csvs_to_output_dir(
        one_pos_output_dir: Path,
        output_dir: Path,
        step_meta: dict[str, Any],
    ) -> None:
        step = int(step_meta.get("step", 0) or 0)
        orbit_index = int(step_meta.get("orbit_index", 0) or 0)
        timestamp_s = float(step_meta.get("timestamp_s", 0.0) or 0.0)
        timestamp_utc = str(step_meta.get("timestamp_utc", ""))
        output_dir.mkdir(parents=True, exist_ok=True)

        # If current-step subfolder exists (e.g. one_pos/<orbit_index>/...),
        # aggregate only that subtree to avoid re-appending prior steps.
        current_step_dir = one_pos_output_dir / str(orbit_index)
        if current_step_dir.exists():
            csv_files = sorted(current_step_dir.rglob("*.csv"))
        else:
            csv_files = sorted(one_pos_output_dir.rglob("*.csv"))
        if not csv_files:
            return

        for src_csv in csv_files:
            dst_csv = output_dir / f"{src_csv.stem}_steps.csv"
            with src_csv.open("r", encoding="utf-8", newline="") as src_f:
                src_rows = [row for row in csv.reader(src_f) if row]
            if not src_rows:
                continue

            payload_len = max(len(row) for row in src_rows)
            if dst_csv.exists() and dst_csv.stat().st_size > 0:
                with dst_csv.open("r", encoding="utf-8", newline="") as f:
                    reader = csv.reader(f)
                    header = next(reader, [])
                existing_payload_len = max(0, len(header) - 4)
                payload_len = max(payload_len, existing_payload_len)

            write_header = (not dst_csv.exists()) or dst_csv.stat().st_size == 0
            with dst_csv.open("a", encoding="utf-8", newline="") as dst_f:
                writer = csv.writer(dst_f)
                if write_header:
                    writer.writerow(
                        [
                            "step",
                            "orbit_index",
                            "timestamp_s",
                            "timestamp_utc",
                        ] + [f"value_{i}" for i in range(payload_len)]
                    )

                for row in src_rows:
                    padded = list(row) + [""] * max(0, payload_len - len(row))
                    writer.writerow(
                        [
                            step,
                            orbit_index,
                            f"{timestamp_s:.6f}",
                            timestamp_utc,
                        ] + padded
                    )

    @staticmethod
    def _parse_pipe_floats(text: str) -> list[float]:
        values: list[float] = []
        for token in str(text).split("|"):
            t = token.strip()
            if not t:
                continue
            try:
                values.append(float(t))
            except ValueError:
                continue
        return values

    @staticmethod
    def plot_orbit_time_vs_decoded_packets(output_dir: Path) -> list[Path]:
        if plt is None:
            return []
        plots_dir = output_dir / "plots"
        plots_dir.mkdir(parents=True, exist_ok=True)

        out_paths: list[Path] = []
        step_csvs = sorted(output_dir.glob("lrfhss_sim_*_steps.csv"))
        for step_csv in step_csvs:
            if "link_budget_agg" in step_csv.stem:
                continue

            series_by_label: dict[str, list[tuple[float, float]]] = {}
            ref_series: list[tuple[float, float]] = []
            with step_csv.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    row_key = str(row.get("value_0", "")).strip()
                    if not row_key:
                        row_key = str(row.get("row_key", "")).strip()
                    try:
                        orbit_t = float(row.get("timestamp_s", 0.0) or 0.0)
                    except (TypeError, ValueError):
                        continue
                    value_keys = [k for k in row.keys() if k.startswith("value_")]
                    value_keys_sorted = sorted(value_keys, key=lambda k: int(k.split("_", 1)[1]))
                    values: list[float] = []
                    for k in value_keys_sorted[1:]:
                        token = str(row.get(k, "")).strip()
                        if not token:
                            continue
                        try:
                            values.append(float(token))
                        except ValueError:
                            continue
                    if not values:
                        values = SatelliteSimulator._parse_pipe_floats(str(row.get("row_values_pipe", "")))
                    if not values:
                        continue

                    row_key_l = row_key.lower()
                    y_value = float(sum(values) / len(values))
                    if row_key_l in {"nodes", "x_equals_y"}:
                        ref_series.append((orbit_t, y_value))
                        continue
                    if "dec_payld" not in row_key_l:
                        continue

                    if row_key_l.startswith("driver-") and row_key_l.endswith("-base"):
                        label = "driver base"
                    elif row_key_l.startswith("driver-"):
                        label = "driver earlydd"
                    elif row_key_l.startswith("lifan-") and row_key_l.endswith("-base"):
                        label = "li-fan base"
                    elif row_key_l.startswith("lifan-"):
                        label = "li-fan earlydd"
                    else:
                        label = row_key
                    series_by_label.setdefault(label, []).append((orbit_t, y_value))

            if not series_by_label and not ref_series:
                continue

            fig, ax = plt.subplots(figsize=(10, 5.5))
            style_map: dict[str, dict[str, Any]] = {
                "driver base": {"color": "#ff7f0e", "linestyle": "--"},
                "driver earlydd": {"color": "#1f77b4", "linestyle": "--"},
                "li-fan base": {"color": "#ff7f0e", "linestyle": "-"},
                "li-fan earlydd": {"color": "#1f77b4", "linestyle": "-"},
            }
            for label, pts in sorted(series_by_label.items()):
                pts_sorted = sorted(pts, key=lambda x: x[0])
                xs = [p[0] for p in pts_sorted]
                ys = [p[1] for p in pts_sorted]
                style = style_map.get(label, {"color": None, "linestyle": "-"})
                ax.plot(
                    xs,
                    ys,
                    marker="o",
                    linewidth=1.8,
                    markersize=3.5,
                    color=style["color"],
                    linestyle=style["linestyle"],
                    label=label,
                )

            if ref_series:
                ref_sorted = sorted(ref_series, key=lambda x: x[0])
                ax.plot(
                    [p[0] for p in ref_sorted],
                    [p[1] for p in ref_sorted],
                    color="black",
                    linewidth=2.0,
                    label="x=y (mean sent packets)",
                )

            ax.set_title(f"CR decoded payloads vs time ({step_csv.stem})")
            ax.set_xlabel("orbit_timestamp_s")
            ax.set_ylabel("Number of Decoded Payloads")
            ax.grid(True, linestyle="-", linewidth=0.5, alpha=0.35)
            ax.legend(fontsize=8)
            fig.tight_layout()

            out_png = plots_dir / f"orbit_time_vs_decoded_packets_{step_csv.stem}.png"
            fig.savefig(out_png, dpi=220)
            plt.close(fig)
            out_paths.append(out_png)

        return out_paths

    def as_dict(self) -> dict[str, int]:
        return {
            "existing_demods": self.existing_demods,
            "idle_demods": self.idle_demods,
            "busy_demods": self.busy_demods,
            "sleep_demods": self.sleep_demods,
        }

    def run(self, args: argparse.Namespace) -> int:
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        one_pos_output_dir = Path(args.one_pos_output_dir)
        one_pos_output_dir.mkdir(parents=True, exist_ok=True)

        steps = int(args.steps) if args.steps is not None else 1
        for step in tqdm(range(max(0, steps)), desc="Steps"):
            one_pos_step_output_dir = Path(args.one_pos_output_dir) / f"step_{step}"
            one_pos_step_output_dir.mkdir(parents=True, exist_ok=True)
            step_meta = self.run_lrfhss_simulator_one_step(args=args, one_pos_output_dir=one_pos_step_output_dir)
            self.append_one_pos_csvs_to_output_dir(
                one_pos_output_dir=one_pos_step_output_dir,
                output_dir=output_dir,
                step_meta=step_meta,
            )

        orbit_decode_plot_paths = self.plot_orbit_time_vs_decoded_packets(output_dir=output_dir)
        for p in orbit_decode_plot_paths:
            print(f"decoded_packets_plot= {p}")

        if bool(getattr(args, "include_elev", True)):
            energy_plot_paths = self.satellite_stepper.plot_elevation_energy_timeseries(output_dir=output_dir / "plots")
            for p in energy_plot_paths:
                print(f"time_vs_energy_plot= {p}")

            demodulator_plot_paths = self.satellite_stepper.plot_elevation_demodulator_timeseries(output_dir=output_dir / "plots")
            for p in demodulator_plot_paths:
                print(f"time_vs_demodulator_plot= {p}")

            combined_energy_plot_path = self.satellite_stepper.plot_combined_elevation_energy_timeseries(output_dir=output_dir / "plots")
            if combined_energy_plot_path is not None:
                print(f"time_vs_energy_plot_combined= {combined_energy_plot_path}")

            combined_demodulator_plot_path = self.satellite_stepper.plot_combined_elevation_demodulator_timeseries(
                output_dir=output_dir / "plots"
            )
            if combined_demodulator_plot_path is not None:
                print(f"time_vs_demodulator_plot_combined= {combined_demodulator_plot_path}")

        print(
            "demod_state_final="
            f"existing:{self.existing_demods},idle:{self.idle_demods},busy:{self.busy_demods},sleep:{self.sleep_demods}"
        )
        return 0


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Run satellite simulator flow with custom demod state transitions (no main.py import).",
    )
    parser.add_argument("--output-dir", type=Path, default=root / "results" / "multi_step_lrfhss")
    parser.add_argument("--one_pos_output_dir", type=Path, default=root / "results" / "one_pos_2_multi_step_lrfhss")
    parser.add_argument("--stepper-output-csv", type=Path, default=root / "results" / "multi_step_lrfhss" / "satellite_steps.csv")
    parser.add_argument("--stepper-current-json", type=Path, default=None)
    parser.add_argument("--population-csv", type=Path, default=root / "Data" / "csv" / "population_data.csv")
    parser.add_argument("--ocean-csv", type=Path, default=root / "Data" / "csv" / "ocean_data.csv")
    parser.add_argument("--node-population-ratio", type=float, default=float(node_population_ratio))
    parser.add_argument("--demd-population-ratio", type=float, default=float(demd_population_ratio))
    parser.add_argument("--minimum-frames", type=int, default=720)
    parser.add_argument("--steps", type=int, default=2)
    parser.add_argument("--step", type=int, default=None)

    parser.add_argument("--existing-demods", type=int, default=None)
    parser.add_argument("--busy-hold-steps", type=int, default=1)
    parser.add_argument("--idle-to-sleep-steps", type=int, default=2)

    parser.add_argument("--sat-lat", type=float, default=None)
    parser.add_argument("--sat-lon", type=float, default=None)
    parser.add_argument("--elev-list", type=float, nargs="+", default=list(elev_list))

    parser.add_argument("--lrfhss-root", type=Path, default=root / "LRFHSS")
    parser.add_argument("--coding-rate", type=int, default=1)
    parser.add_argument("--metric", type=str, default="dec_payld")
    parser.add_argument("--drop-mode", type=str, default="rlydd", choices=["rlydd", "hdrdd", "headerdrop"])
    parser.add_argument("--runs-per-node", type=int, default=1)
    parser.add_argument("--include-lifan", action="store_true")
    parser.add_argument("--include-infp", action="store_true")
    parser.add_argument("--inf-demods", type=int, default=None)
    parser.add_argument("--node-min", type=float, default=None)
    parser.add_argument("--node-max", type=float, default=10000.0)
    parser.add_argument("--x-min", type=float, default=100)
    parser.add_argument("--x-max", type=float, default=10000.0)
    parser.add_argument("--y-min", type=float, default=None)
    parser.add_argument("--y-max", type=float, default=2600)
    parser.add_argument("--link-budget-log", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--plot-enabled", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--include-elev", action=argparse.BooleanOptionalAction, default=False)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    stepper_json = args.stepper_current_json or (Path(args.output_dir) / "satellite_steps_current_pos.json")
    stepper = SatelliteStepper(
        output_csv_path=Path(args.stepper_output_csv),
        population_csv_path=Path(args.population_csv),
        ocean_csv_path=Path(args.ocean_csv),
        current_pos_json_path=Path(stepper_json),
        node_population_ratio=float(args.node_population_ratio),
        demd_population_ratio=float(args.demd_population_ratio),
        minimum_frames=int(args.minimum_frames),
        elev_list=[float(v) for v in args.elev_list],
    )

    simulator = SatelliteSimulator(
        existing_demods=args.existing_demods,
        satellite_stepper=stepper,
        step=args.step,
        busy_hold_steps=args.busy_hold_steps,
        idle_to_sleep_steps=args.idle_to_sleep_steps,
    )
    return simulator.run(args)


if __name__ == "__main__":
    raise SystemExit(main())
