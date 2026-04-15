import math

from base.base import GAIN_RX, GAIN_TX, dBm2mW, get_FS_pathloss, mW2dBm


class RadioLinkBudget:
    @staticmethod
    def transmitted_power_mw(tx_power_dbm: float) -> float:
        return float(dBm2mW(float(tx_power_dbm)))

    @staticmethod
    def attenuation_linear(distance_m: float, carrier_hz: float) -> float:
        return float(get_FS_pathloss(float(distance_m), float(carrier_hz)))

    @staticmethod
    def attenuation_db(distance_m: float, carrier_hz: float) -> float:
        gain = max(RadioLinkBudget.attenuation_linear(distance_m, carrier_hz), 1e-15)
        return float(-10.0 * math.log10(gain))

    @staticmethod
    def received_power_mw(
        tx_power_dbm: float,
        distance_m: float,
        carrier_hz: float,
        tx_gain_db: float = GAIN_TX,
        rx_gain_db: float = GAIN_RX,
    ) -> float:
        tx_mw = float(dBm2mW(float(tx_power_dbm)))
        tx_gain_mw = float(dBm2mW(float(tx_gain_db)))
        rx_gain_mw = float(dBm2mW(float(rx_gain_db)))
        channel_gain = RadioLinkBudget.attenuation_linear(distance_m, carrier_hz)
        return float(tx_mw * tx_gain_mw * rx_gain_mw * channel_gain)

    @staticmethod
    def received_power_dbm(
        tx_power_dbm: float,
        distance_m: float,
        carrier_hz: float,
        tx_gain_db: float = GAIN_TX,
        rx_gain_db: float = GAIN_RX,
    ) -> float:
        return float(
            mW2dBm(
                RadioLinkBudget.received_power_mw(
                    tx_power_dbm=tx_power_dbm,
                    distance_m=distance_m,
                    carrier_hz=carrier_hz,
                    tx_gain_db=tx_gain_db,
                    rx_gain_db=rx_gain_db,
                )
            )
        )
