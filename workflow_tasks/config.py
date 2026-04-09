from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class PipelineConfig:
    node_loads: list[int]
    demodulator_options: list[int]
    runs_per_point: int
    visibility_min_elev_deg: float
    output_dir: Path
    seed: int
    export_csv: bool
    generate_plots: bool
    battery_initial_percent: float
    low_battery_threshold: float
    idle_battery_threshold: float
    high_charge_threshold: float
    scenario_steps: int
    step_seconds: float
    panel_area_m2: float
    solar_irradiance_w_m2: float
    panel_efficiency: float
    power_conditioning_efficiency: float
    battery_capacity_wh: float
    battery_max_charge_w: float
    battery_charge_efficiency: float
    battery_discharge_efficiency: float
    demod_tx_capacity_per_step: float
    base_power_w: float
    rf_frontend_power_w: float
    min_demod_allocation: int
    max_demod_step_change: int
    policy_labels: list[str]
    lrfhss_spreading_label: str
    lrfhss_coding_rate: str
    lrfhss_fragmentation_fragments: int
    lrfhss_payload_bytes: int
    center_frequency_hz: float
    noise_bandwidth_hz: float
    tx_power_dbm: float
    tx_gain_dbi: float
    rx_gain_dbi: float
    implementation_loss_db: float
    noise_figure_db: float


def initialize_simulation_parameters(
    output_dir: Path,
    seed: int,
    node_min: int,
    node_max: int,
    node_points: int,
    demodulator_options: list[int],
    nodes_list: list[int] | None,
    export_csv: bool,
    generate_plots: bool,
    battery_initial_percent: float,
    low_battery_threshold: float,
    idle_battery_threshold: float,
    high_charge_threshold: float,
    runs_per_point: int,
    scenario_steps: int,
    step_seconds: float,
    panel_area_m2: float,
    solar_irradiance_w_m2: float,
    panel_efficiency: float,
    power_conditioning_efficiency: float,
    battery_capacity_wh: float,
    battery_max_charge_w: float,
    battery_charge_efficiency: float,
    battery_discharge_efficiency: float,
    demod_tx_capacity_per_step: float,
    base_power_w: float,
    rf_frontend_power_w: float,
    min_demod_allocation: int,
    max_demod_step_change: int,
) -> PipelineConfig:
    if nodes_list:
        loads = sorted(set(int(v) for v in nodes_list if int(v) >= 0))
    else:
        loads = [int(round(v)) for v in np.logspace(np.log10(node_min), np.log10(node_max), num=node_points)]
        loads = sorted(set(loads))
    return PipelineConfig(
        node_loads=loads,
        demodulator_options=demodulator_options,
        runs_per_point=max(1, int(runs_per_point)),
        visibility_min_elev_deg=10.0,
        output_dir=output_dir,
        seed=seed,
        export_csv=export_csv,
        generate_plots=generate_plots,
        battery_initial_percent=battery_initial_percent,
        low_battery_threshold=low_battery_threshold,
        idle_battery_threshold=idle_battery_threshold,
        high_charge_threshold=high_charge_threshold,
        scenario_steps=max(1, int(scenario_steps)),
        step_seconds=float(step_seconds),
        panel_area_m2=float(panel_area_m2),
        solar_irradiance_w_m2=float(solar_irradiance_w_m2),
        panel_efficiency=float(panel_efficiency),
        power_conditioning_efficiency=float(power_conditioning_efficiency),
        battery_capacity_wh=float(battery_capacity_wh),
        battery_max_charge_w=float(battery_max_charge_w),
        battery_charge_efficiency=float(battery_charge_efficiency),
        battery_discharge_efficiency=float(battery_discharge_efficiency),
        demod_tx_capacity_per_step=float(demod_tx_capacity_per_step),
        base_power_w=float(base_power_w),
        rf_frontend_power_w=float(rf_frontend_power_w),
        min_demod_allocation=max(0, int(min_demod_allocation)),
        max_demod_step_change=max(1, int(max_demod_step_change)),
        policy_labels=["EnergyAware", "NonEnergyAware"],
        lrfhss_spreading_label="LR-FHSS (grid-hopping)",
        lrfhss_coding_rate="1/3",
        lrfhss_fragmentation_fragments=6,
        lrfhss_payload_bytes=15,
        center_frequency_hz=868_000_000.0,
        noise_bandwidth_hz=488.0,
        tx_power_dbm=14.0,
        tx_gain_dbi=0.0,
        rx_gain_dbi=2.0,
        implementation_loss_db=2.0,
        noise_figure_db=5.0,
    )
