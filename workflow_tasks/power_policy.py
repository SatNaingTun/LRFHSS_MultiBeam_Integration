from __future__ import annotations

from demodulator_power import DemodulatorPowerModel

import numpy as np

from .config import PipelineConfig

DEMOD_POWER_MODEL = DemodulatorPowerModel()


def compute_generated_power_w(
    sunlit: bool,
    panel_area_m2: float,
    solar_irradiance_w_m2: float,
    panel_efficiency: float,
    power_conditioning_efficiency: float,
) -> float:
    if not sunlit:
        return 0.0
    panel_raw_w = float(panel_area_m2 * solar_irradiance_w_m2 * panel_efficiency)
    return float(panel_raw_w * power_conditioning_efficiency)


def compute_power_balance(
    generated_power_w: float,
    power_consumption_watts: float,
    battery_percent: float,
    battery_max_charge_w: float,
) -> tuple[bool, float, float, float]:
    surplus_watts = float(generated_power_w - power_consumption_watts)

    if battery_percent >= 99.0:
        charge_acceptance_scale = 0.0
    elif battery_percent >= 95.0:
        charge_acceptance_scale = 0.25
    elif battery_percent >= 90.0:
        charge_acceptance_scale = 0.5
    else:
        charge_acceptance_scale = 1.0

    max_charge_watts = float(battery_max_charge_w * charge_acceptance_scale)
    charging_power_watts = float(min(max(surplus_watts, 0.0), max_charge_watts))
    discharging_power_watts = float(max(-surplus_watts, 0.0))
    net_power_watts = float(charging_power_watts - discharging_power_watts)
    charging = bool(net_power_watts > 0.0)
    return charging, charging_power_watts, discharging_power_watts, net_power_watts


def update_battery_percentage(
    battery_percent: float,
    net_power_watts: float,
    step_seconds: float,
    battery_capacity_wh: float,
    battery_charge_efficiency: float,
    battery_discharge_efficiency: float,
) -> float:
    step_hours = float(step_seconds / 3600.0)
    delta_wh = float(net_power_watts * step_hours)
    if delta_wh >= 0.0:
        delta_wh *= battery_charge_efficiency
    else:
        delta_wh /= max(battery_discharge_efficiency, 1e-9)
    delta_percent = float((delta_wh / battery_capacity_wh) * 100.0)
    new_pct = float(battery_percent + delta_percent)
    return float(max(0.0, min(100.0, new_pct)))


def compute_power_consumption(
    visible: bool,
    allocated_demods: int,
    tx_count: int,
    demod_tx_capacity_per_step: float,
    base_power_w: float,
    rf_frontend_power_w: float,
) -> tuple[float, float, float]:
    demod_result = DEMOD_POWER_MODEL.evaluate(
        visible=visible,
        allocated_demods=allocated_demods,
        tx_count=tx_count,
        demod_tx_capacity_per_step=demod_tx_capacity_per_step,
    )
    total_w = float(base_power_w + rf_frontend_power_w + demod_result.total_demod_power_w)
    return total_w, demod_result.mean_demod_power_w, demod_result.utilization


def allocate_demodulators(
    policy_label: str,
    requested_demods: int,
    visible: bool,
    battery_percent: float,
    idle_battery_threshold: float,
    min_demod_allocation: int,
    max_demod_step_change: int,
    previous_allocated_demods: int,
) -> int:
    if (not visible) or requested_demods <= 0:
        return 0

    if policy_label == "NonEnergyAware":
        target = int(requested_demods)
    else:
        if battery_percent < idle_battery_threshold:
            target = max(min_demod_allocation, int(round(requested_demods * 0.35)))
        elif battery_percent < 60.0:
            target = max(min_demod_allocation, int(round(requested_demods * 0.60)))
        elif battery_percent < 80.0:
            target = max(min_demod_allocation, int(round(requested_demods * 0.80)))
        else:
            target = int(requested_demods)

    delta = target - previous_allocated_demods
    if abs(delta) > max_demod_step_change:
        target = previous_allocated_demods + int(np.sign(delta) * max_demod_step_change)
    return int(max(0, min(requested_demods, target)))


def simulate_power_policy(
    cfg: PipelineConfig,
    nodes: int,
    requested_demods: int,
    packet_count: int,
    selected_frame: int,
    visibility_mask: np.ndarray,
    policy_label: str,
) -> dict:
    del nodes
    allocated_demods = int(requested_demods)
    frame_count = len(visibility_mask)

    allocated_trace = []
    power_trace_w = []
    utilization_trace = []
    tx_trace = []
    visible_trace = []
    terminal_demod_power_w = 0.0

    for step in range(cfg.scenario_steps):
        frame = (selected_frame + step) % frame_count
        visible = bool(visibility_mask[frame])
        tx_count = int(packet_count if visible else 0)

        allocated_demods = allocate_demodulators(
            policy_label=policy_label,
            requested_demods=requested_demods,
            visible=visible,
            battery_percent=100.0,
            idle_battery_threshold=cfg.idle_battery_threshold,
            min_demod_allocation=cfg.min_demod_allocation,
            max_demod_step_change=cfg.max_demod_step_change,
            previous_allocated_demods=allocated_demods,
        )
        power_consumption_w, demod_power_w, utilization = compute_power_consumption(
            visible=visible,
            allocated_demods=allocated_demods,
            tx_count=tx_count,
            demod_tx_capacity_per_step=cfg.demod_tx_capacity_per_step,
            base_power_w=cfg.base_power_w,
            rf_frontend_power_w=cfg.rf_frontend_power_w,
        )
        terminal_demod_power_w = demod_power_w
        allocated_trace.append(float(allocated_demods))
        power_trace_w.append(float(power_consumption_w))
        utilization_trace.append(float(utilization))
        tx_trace.append(float(tx_count))
        visible_trace.append(1.0 if visible else 0.0)

    return {
        "policy_label": policy_label,
        "mean_allocated_demods": float(np.mean(allocated_trace)),
        "mean_power_consumption_watts": float(np.mean(power_trace_w)),
        "mean_demod_utilization": float(np.mean(utilization_trace)),
        "mean_tx_count_per_step": float(np.mean(tx_trace)),
        "visibility_ratio": float(np.mean(visible_trace)),
        "terminal_allocated_demods": int(round(allocated_trace[-1])),
        "terminal_demod_power_watts": float(terminal_demod_power_w),
    }
