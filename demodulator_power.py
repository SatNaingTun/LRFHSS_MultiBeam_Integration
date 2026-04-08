import math
from dataclasses import dataclass


@dataclass(frozen=True)
class DemodulatorPowerResult:
    sleep_demods: int
    idle_demods: int
    busy_demods: int
    mean_demod_power_w: float
    total_demod_power_w: float
    utilization: float


class DemodulatorPowerModel:
    def __init__(
        self,
        idle_power_w: float = 0.12,
        busy_power_w: float = 0.80,
    ) -> None:
        self.idle_power_w = float(idle_power_w)
        self.busy_power_w = float(busy_power_w)

    @staticmethod
    def _utilization(tx_count: int, allocated_demods: int, demod_tx_capacity_per_step: float) -> float:
        if allocated_demods <= 0:
            return 0.0
        capacity = float(max(1.0, allocated_demods * demod_tx_capacity_per_step))
        return float(min(1.0, float(max(0, tx_count)) / capacity))

    @staticmethod
    def _state_counts(
        visible: bool,
        allocated_demods: int,
        tx_count: int,
        demod_tx_capacity_per_step: float,
    ) -> tuple[int, int, int]:
        if allocated_demods <= 0:
            return 0, 0, 0
        if not visible:
            return 0, int(allocated_demods), 0

        cap_per_demod = float(max(1.0, demod_tx_capacity_per_step))
        busy_demods = int(min(allocated_demods, math.ceil(float(max(0, tx_count)) / cap_per_demod)))
        idle_demods = int(max(0, allocated_demods - busy_demods))
        return 0, idle_demods, busy_demods

    def evaluate(
        self,
        visible: bool,
        allocated_demods: int,
        tx_count: int,
        demod_tx_capacity_per_step: float,
    ) -> DemodulatorPowerResult:
        utilization = self._utilization(
            tx_count=tx_count,
            allocated_demods=allocated_demods,
            demod_tx_capacity_per_step=demod_tx_capacity_per_step,
        )
        sleep_demods, idle_demods, busy_demods = self._state_counts(
            visible=visible,
            allocated_demods=allocated_demods,
            tx_count=tx_count,
            demod_tx_capacity_per_step=demod_tx_capacity_per_step,
        )
        total_demod_power_w = float(idle_demods * self.idle_power_w + busy_demods * self.busy_power_w)
        mean_demod_power_w = float(total_demod_power_w / max(allocated_demods, 1))
        return DemodulatorPowerResult(
            sleep_demods=sleep_demods,
            idle_demods=idle_demods,
            busy_demods=busy_demods,
            mean_demod_power_w=mean_demod_power_w,
            total_demod_power_w=total_demod_power_w,
            utilization=utilization,
        )
