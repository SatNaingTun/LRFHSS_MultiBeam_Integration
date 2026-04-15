import numpy as np

from base.base import AWGN_VAR_DB, dBm2mW, mW2dBm


class RadioSignalQuality:
    @staticmethod
    def noise_power_mw(noise_floor_dbm: float = AWGN_VAR_DB) -> float:
        return float(dBm2mW(float(noise_floor_dbm)))

    @staticmethod
    def interference_power_mw(total_power_mw: float, signal_power_mw: float) -> float:
        return float(max(float(total_power_mw) - float(signal_power_mw), 0.0))

    @staticmethod
    def snr_db(signal_power_mw: float, noise_power_mw: float) -> float:
        den = max(float(noise_power_mw), 1e-15)
        return float(mW2dBm(float(signal_power_mw) / den))

    @staticmethod
    def sinr_db(signal_power_mw: float, interference_power_mw: float, noise_power_mw: float) -> float:
        den = max(float(interference_power_mw) + float(noise_power_mw), 1e-15)
        return float(mW2dBm(float(signal_power_mw) / den))

    @staticmethod
    def estimate_signal_and_interference(
        headers: np.ndarray,
        fragments: np.ndarray,
    ) -> tuple[float, np.ndarray, np.ndarray]:
        # Mean over frequency slots -> one power value per symbol-time.
        avg_headers = np.mean(headers, axis=1)
        avg_fragments = np.mean(fragments, axis=1)

        all_symbols = np.concatenate((np.ravel(avg_headers), np.ravel(avg_fragments)))
        th1 = float(np.median(all_symbols))

        filtered = all_symbols[all_symbols <= th1]
        if filtered.size == 0:
            est_signal_power = th1
        else:
            est_signal_power = float(np.mean(filtered))
        est_signal_power = max(est_signal_power, 1e-15)

        headers_interference = np.maximum(avg_headers - est_signal_power, 0.0)
        fragments_interference = np.maximum(avg_fragments - est_signal_power, 0.0)

        return est_signal_power, headers_interference, fragments_interference
