import csv
import random
from pathlib import Path

import numpy as np

from LoRaNetwork import LoRaNetwork
from base.RadioLinkBudget import RadioLinkBudget
from base.RadioSignalQuality import RadioSignalQuality
from base.base import (
    CR,
    OBW_BW,
    OCW_FC,
    freqGranularity,
    linkBudgetLog,
    numGrids,
    numOBW,
    numOCW,
    runs,
    simTime,
    timeGranularity,
)

try:
    from tqdm import tqdm
except ModuleNotFoundError:  # pragma: no cover
    tqdm = None

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ModuleNotFoundError:  # pragma: no cover
    plt = None


def _format_link_budget_value(value: float) -> str:
    x = float(value)
    if np.isnan(x) or np.isinf(x):
        return str(x)
    ax = abs(x)
    if ax != 0.0 and ax < 1e-3:
        return f"{x:.6e}"
    return f"{x:.6f}"


def _drop_mode_flags(drop_mode: str) -> tuple[bool, bool, bool]:
    # base   -> early decode ON, early drop OFF, header drop OFF
    # rlydd  -> early decode ON, early drop ON,  header drop OFF
    # hdrdd  -> early decode ON, early drop ON,  header drop ON
    if drop_mode == "base":
        return True, False, False
    if drop_mode == "rlydd":
        return True, True, False
    if drop_mode == "hdrdd":
        return True, True, True
    raise ValueError(f"Unsupported drop_mode: {drop_mode}")


def _resolve_nodes(
    node_min: float | None = None,
    node_max: float | None = None,
    selected_nodes: list[float] | None = None,
    node_points: int = 40,
) -> list[int]:
    if selected_nodes:
        nodes = sorted(set(int(round(float(v))) for v in selected_nodes if float(v) > 0))
    else:
        n_min = float(10.0 if node_min is None else node_min)
        n_max = float(1000.0 if node_max is None else node_max)
        nodes = [int(round(v)) for v in np.logspace(np.log10(n_min), np.log10(n_max), num=max(2, int(node_points)))]
        nodes = sorted(set(v for v in nodes if v > 0))
    if not nodes:
        raise ValueError("No positive node values available for simulation.")
    return nodes


def _metric_from_network(network, metric: str) -> float:
    if metric == "dec_payld":
        return float(network.get_decoded_hrd_pld())
    if metric == "dec_pckts":
        return float(network.get_decoded_hdr())
    raise ValueError(f"Unsupported metric: {metric}")


def _write_link_budget_rows(
    network: LoRaNetwork,
    run_index: int,
    nodes: int,
    familyname: str,
    drop_mode: str,
    out_csv: Path,
) -> None:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    power_matrix = network.get_rcvM(network.TXset, power=True, dynamic=False)
    noise_mw = RadioSignalQuality.noise_power_mw()

    file_exists = out_csv.exists() and out_csv.stat().st_size > 0
    with out_csv.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(
                [
                    "run",
                    "nodes",
                    "family",
                    "drop_mode",
                    "tx_id",
                    "node_id",
                    "ocw",
                    "start_slot",
                    "distance_m",
                    "tx_power_dbm",
                    "tx_power_mw",
                    "carrier_hz",
                    "attenuation_linear",
                    "attenuation_db",
                    "rx_power_mw",
                    "rx_power_dbm",
                    "noise_power_mw",
                    "total_power_mw",
                    "interference_mw",
                    "snr_db",
                    "sinr_db",
                ]
            )

        for tx in network.TXset:
            doppler_shift = round(tx.dopplerShift[0] / network.freqPerSlot)
            start_freq = network.baseFreq + tx.sequence[0] * network.freqGranularity + doppler_shift
            end_freq = start_freq + network.freqGranularity
            end_time = tx.startSlot + network.headerSlots
            carrier_hz = OCW_FC + start_freq * (OBW_BW / network.freqGranularity)

            tx_power_mw = RadioLinkBudget.transmitted_power_mw(tx.power)
            attenuation_linear = RadioLinkBudget.attenuation_linear(tx.distance, carrier_hz)
            attenuation_db = RadioLinkBudget.attenuation_db(tx.distance, carrier_hz)
            rx_power_mw = RadioLinkBudget.received_power_mw(tx.power, tx.distance, carrier_hz)
            rx_power_dbm = RadioLinkBudget.received_power_dbm(tx.power, tx.distance, carrier_hz)

            block = power_matrix[tx.ocw, start_freq:end_freq, tx.startSlot:end_time]
            total_power_mw = float(np.mean(block)) if block.size > 0 else rx_power_mw
            interference_mw = RadioSignalQuality.interference_power_mw(total_power_mw, rx_power_mw)
            snr_db = RadioSignalQuality.snr_db(rx_power_mw, noise_mw)
            sinr_db = RadioSignalQuality.sinr_db(rx_power_mw, interference_mw, noise_mw)

            writer.writerow(
                [
                    int(run_index),
                    int(nodes),
                    str(familyname),
                    str(drop_mode),
                    int(tx.id),
                    int(tx.node_id),
                    int(tx.ocw),
                    int(tx.startSlot),
                    float(tx.distance),
                    float(tx.power),
                    float(tx_power_mw),
                    float(carrier_hz),
                    float(attenuation_linear),
                    float(attenuation_db),
                    float(rx_power_mw),
                    float(rx_power_dbm),
                    float(noise_mw),
                    float(total_power_mw),
                    float(interference_mw),
                    float(snr_db),
                    float(sinr_db),
                ]
            )

def _aggregate_link_budget_for_network(network: LoRaNetwork) -> dict[str, float]:
    power_matrix = network.get_rcvM(network.TXset, power=True, dynamic=False)
    count_matrix = network.get_rcvM(network.TXset, power=False, dynamic=False)
    noise_samples = power_matrix[count_matrix == 0]
    if noise_samples.size > 0:
        noise_mw = float(np.mean(noise_samples))
    else:
        noise_mw = RadioSignalQuality.noise_power_mw()

    tx_power_mw_vals: list[float] = []
    attenuation_linear_vals: list[float] = []
    attenuation_db_vals: list[float] = []
    rx_power_mw_vals: list[float] = []
    rx_power_dbm_vals: list[float] = []
    total_power_mw_vals: list[float] = []
    interference_mw_vals: list[float] = []
    snr_db_vals: list[float] = []
    sinr_db_vals: list[float] = []

    for tx in network.TXset:
        doppler_shift = round(tx.dopplerShift[0] / network.freqPerSlot)
        start_freq = network.baseFreq + tx.sequence[0] * network.freqGranularity + doppler_shift
        end_freq = start_freq + network.freqGranularity
        end_time = tx.startSlot + network.headerSlots
        carrier_hz = OCW_FC + start_freq * (OBW_BW / network.freqGranularity)

        tx_power_mw = RadioLinkBudget.transmitted_power_mw(tx.power)
        attenuation_linear = RadioLinkBudget.attenuation_linear(tx.distance, carrier_hz)
        attenuation_db = RadioLinkBudget.attenuation_db(tx.distance, carrier_hz)
        rx_power_mw = RadioLinkBudget.received_power_mw(tx.power, tx.distance, carrier_hz)
        rx_power_dbm = RadioLinkBudget.received_power_dbm(tx.power, tx.distance, carrier_hz)

        block = power_matrix[tx.ocw, start_freq:end_freq, tx.startSlot:end_time]
        total_power_mw = float(np.mean(block)) if block.size > 0 else rx_power_mw
        # Interference from co-channel users only (exclude desired signal and noise).
        interference_mw = float(max(total_power_mw - rx_power_mw - noise_mw, 0.0))
        snr_db = RadioSignalQuality.snr_db(rx_power_mw, noise_mw)
        sinr_db = RadioSignalQuality.sinr_db(rx_power_mw, interference_mw, noise_mw)

        tx_power_mw_vals.append(float(tx_power_mw))
        attenuation_linear_vals.append(float(attenuation_linear))
        attenuation_db_vals.append(float(attenuation_db))
        rx_power_mw_vals.append(float(rx_power_mw))
        rx_power_dbm_vals.append(float(rx_power_dbm))
        total_power_mw_vals.append(float(total_power_mw))
        interference_mw_vals.append(float(interference_mw))
        snr_db_vals.append(float(snr_db))
        sinr_db_vals.append(float(sinr_db))

    def _mean(vals: list[float]) -> float:
        return float(np.mean(np.array(vals, dtype=float))) if vals else float("nan")

    return {
        "tx_power_mw": _mean(tx_power_mw_vals),
        "attenuation_linear": _mean(attenuation_linear_vals),
        "attenuation_db": _mean(attenuation_db_vals),
        "rx_power_mw": _mean(rx_power_mw_vals),
        "rx_power_dbm": _mean(rx_power_dbm_vals),
        "noise_power_mw": float(noise_mw),
        "total_power_mw": _mean(total_power_mw_vals),
        "interference_mw": _mean(interference_mw_vals),
        "snr_db": _mean(snr_db_vals),
        "sinr_db": _mean(sinr_db_vals),
    }


def run_sim(
    nodes: int,
    num_decoders: int,
    drop_mode: str,
    familyname: str = "driver",
    coding_rate: int = CR,
    metric: str = "dec_payld",
    runs_per_node: int | None = None,
    sim_time: int = simTime,
    num_ocw: int = numOCW,
    num_obw: int = numOBW,
    num_grids: int = numGrids,
    time_granularity: int = timeGranularity,
    freq_granularity: int = freqGranularity,
    link_budget_log: bool = linkBudgetLog,
    return_link_budget_summary: bool = False,
    control: bool | None = None,
) -> float | tuple[float, dict[str, float]]:
    use_earlydecode, use_earlydrop, use_headerdrop = _drop_mode_flags(drop_mode)
    power = False
    dynamic = False
    collision_method = "strict"

    network = LoRaNetwork(
        int(nodes),
        familyname,
        int(num_ocw),
        int(num_obw),
        int(num_grids),
        int(coding_rate),
        int(time_granularity),
        int(freq_granularity),
        int(sim_time),
        int(num_decoders),
        bool(use_earlydecode),
        bool(use_earlydrop),
        bool(use_headerdrop),
        collision_method,
    )

    if control is not None:
        link_budget_log = bool(control)

    local_runs = max(1, int(runs if runs_per_node is None else runs_per_node))
    vals: list[float] = []
    run_link_summaries: list[dict[str, float]] = []
    run_iter = range(local_runs)
    if tqdm is not None and local_runs > 1:
        run_iter = tqdm(run_iter, desc=f"Running simulations for {local_runs} runs", leave=False)
    for r in run_iter:
        random.seed(2 * r)
        if bool(link_budget_log) or bool(return_link_budget_summary):
            current_summary = _aggregate_link_budget_for_network(network)
            if bool(return_link_budget_summary):
                run_link_summaries.append(current_summary)
        network.get_predecoded_data()
        network.run(power, dynamic)
        vals.append(_metric_from_network(network, metric=metric))
        network.restart()
    metric_value = float(np.mean(np.array(vals, dtype=float)))
    if not bool(return_link_budget_summary):
        return metric_value

    keys = [
        "tx_power_mw",
        "attenuation_linear",
        "attenuation_db",
        "rx_power_mw",
        "rx_power_dbm",
        "noise_power_mw",
        "total_power_mw",
        "interference_mw",
        "snr_db",
        "sinr_db",
    ]
    final_summary: dict[str, float] = {}
    for k in keys:
        final_summary[k] = float(
            np.mean(np.array([float(d.get(k, float("nan"))) for d in run_link_summaries], dtype=float))
        )
    return metric_value, final_summary

    # vals: list[float] = []
    # network.get_predecoded_data()
    # network.run(power, dynamic)
    # vals.append(_metric_from_network(network, metric=metric))
    # network.restart()
    # return float(vals[0])

def runsim2csv(
    num_decoders: int,
    drop_mode: str,
    filename: str | Path,
    coding_rate: int = CR,
    metric: str = "dec_payld",
    include_lifan: bool = False,
    include_infp: bool = False,
    inf_demods: int | None = None,
    node_min: float | None = None,
    node_max: float | None = None,
    selected_nodes: list[float] | None = None,
    node_points: int = 40,
    runs_per_node: int | None = None,
    sim_time: int = simTime,
    num_ocw: int = numOCW,
    num_obw: int = numOBW,
    num_grids: int = numGrids,
    time_granularity: int = timeGranularity,
    freq_granularity: int = freqGranularity,
    link_budget_log: bool = linkBudgetLog,
    
) -> Path:
    if link_budget_log is not None:
        link_budget_log = bool(link_budget_log)

    nodes = _resolve_nodes(
        node_min=node_min,
        node_max=node_max,
        selected_nodes=selected_nodes,
        node_points=node_points,
    )
    families = ["driver"] + (["lifan"] if include_lifan else [])
    link_budget_agg_csv = Path(filename).with_name(f"{Path(filename).stem}_link_budget_agg.csv")
    if bool(link_budget_log):
        link_budget_agg_csv.parent.mkdir(parents=True, exist_ok=True)
        link_budget_agg_csv.write_text("", encoding="utf-8")

    rows: list[tuple[str, list[float]]] = []
    node_vals = [float(v) for v in nodes]
    rows.append(("nodes", node_vals))
    rows.append(("x_equals_y", node_vals))
    agg_rows: dict[str, list[float]] = {}

    family_iter = families
    if tqdm is not None:
        family_iter = tqdm(families, desc=f"Processing families demods {int(num_decoders)}", leave=False)
    for family in family_iter:
        base_vals: list[float] = []
        dd_vals: list[float] = []
        inf_vals: list[float] = []

        iterator = nodes
        if tqdm is not None:
            iterator = tqdm(nodes, desc=f"{family} CR{int(coding_rate)} {drop_mode}", leave=False)

        for n in iterator:
            base_result = run_sim(
                    nodes=n,
                    num_decoders=num_decoders,
                    drop_mode="base",
                    familyname=family,
                    coding_rate=coding_rate,
                    metric=metric,
                    runs_per_node=runs_per_node,
                    sim_time=sim_time,
                    num_ocw=num_ocw,
                    num_obw=num_obw,
                    num_grids=num_grids,
                    time_granularity=time_granularity,
                    freq_granularity=freq_granularity,
                    link_budget_log=link_budget_log,
                    return_link_budget_summary=link_budget_log,
                )
            base_summary: dict[str, float] | None = None
            base_metric_val: float
            if bool(link_budget_log):
                base_metric_val, base_summary = base_result  # type: ignore[misc]
            else:
                base_metric_val = float(base_result)  # type: ignore[arg-type]
            base_vals.append(base_metric_val)

            dd_result = run_sim(
                    nodes=n,
                    num_decoders=num_decoders,
                    drop_mode=drop_mode,
                    familyname=family,
                    coding_rate=coding_rate,
                    metric=metric,
                    runs_per_node=runs_per_node,
                    sim_time=sim_time,
                    num_ocw=num_ocw,
                    num_obw=num_obw,
                    num_grids=num_grids,
                    time_granularity=time_granularity,
                    freq_granularity=freq_granularity,
                    link_budget_log=link_budget_log,
                    return_link_budget_summary=link_budget_log,
                )
            dd_summary: dict[str, float] | None = None
            dd_metric_val: float
            if bool(link_budget_log):
                dd_metric_val, dd_summary = dd_result  # type: ignore[misc]
            else:
                dd_metric_val = float(dd_result)  # type: ignore[arg-type]
            dd_vals.append(dd_metric_val)

            if bool(link_budget_log) and base_summary is not None and dd_summary is not None:
                base_key = f"{family}-CR{int(coding_rate)}-{int(num_decoders)}p-{metric}-base"
                dd_key = f"{family}-CR{int(coding_rate)}-{int(num_decoders)}p-{metric}-{drop_mode}"
                for mkey, mval in base_summary.items():
                    agg_rows.setdefault(f"{base_key}-{mkey}", []).append(float(mval))
                for mkey, mval in dd_summary.items():
                    agg_rows.setdefault(f"{dd_key}-{mkey}", []).append(float(mval))

            if include_infp:
                inf_count = int(num_decoders) if inf_demods is None else max(int(num_decoders), int(inf_demods))
                inf_vals.append(
                    run_sim(
                        nodes=n,
                        num_decoders=inf_count,
                        drop_mode=drop_mode,
                        familyname=family,
                        coding_rate=coding_rate,
                        metric=metric,
                        runs_per_node=runs_per_node,
                        sim_time=sim_time,
                        num_ocw=num_ocw,
                        num_obw=num_obw,
                        num_grids=num_grids,
                        time_granularity=time_granularity,
                        freq_granularity=freq_granularity,
                        link_budget_log=link_budget_log,
                    )
                )

        rows.append((f"{family}-CR{int(coding_rate)}-{int(num_decoders)}p-{metric}-base", base_vals))
        rows.append((f"{family}-CR{int(coding_rate)}-{int(num_decoders)}p-{metric}-{drop_mode}", dd_vals))
        if include_infp:
            rows.append((f"{family}-CR{int(coding_rate)}-infp-{metric}", inf_vals))

    out = Path(filename)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        for key, vals in rows:
            writer.writerow([key] + [f"{float(v if v is not None else 0):.6f}" for v in vals])
    if bool(link_budget_log):
        with link_budget_agg_csv.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["nodes"] + [f"{float(v):.6f}" for v in node_vals])
            for key, vals in agg_rows.items():
                writer.writerow([key] + [_format_link_budget_value(float(v)) for v in vals])
        print(f"[lrfhss] Link-budget aggregate CSV: {link_budget_agg_csv.resolve()}")
    return out


def _load_runsim_csv_rows(path: Path) -> dict[str, np.ndarray]:
    rows: dict[str, np.ndarray] = {}
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            key = str(row[0]).strip()
            vals: list[float] = []
            for tok in row[1:]:
                text = str(tok).strip()
                if not text:
                    continue
                vals.append(float(text))
            rows[key] = np.array(vals, dtype=float)
    return rows


def _plot_runsim_rows(
    rows: dict[str, np.ndarray],
    out_png: Path,
    num_decoders: int,
    coding_rate: int,
    metric: str,
    drop_mode: str,
    include_lifan: bool,
    include_infp: bool,
    x_min: float | None = None,
    x_max: float | None = None,
    y_min: float | None = None,
    y_max: float | None = None,
    title: str | None = None,
) -> Path:
    if plt is None:
        raise ModuleNotFoundError("matplotlib is required for plotting. Install with: pip install matplotlib")

    nodes = rows.get("nodes")
    if nodes is None or len(nodes) <= 0:
        raise ValueError("CSV rows do not contain 'nodes' for plotting.")

    fig, ax = plt.subplots(figsize=(10, 8))
    suffix_base = f"CR{int(coding_rate)}-{int(num_decoders)}p-{metric}-base"
    suffix_drop = f"CR{int(coding_rate)}-{int(num_decoders)}p-{metric}-{drop_mode}"

    if include_lifan:
        lifan_base = rows.get(f"lifan-{suffix_base}")
        lifan_drop = rows.get(f"lifan-{suffix_drop}")
        if lifan_base is not None and lifan_drop is not None:
            ax.plot(nodes, lifan_base, color="#ff7f0e", linewidth=2, label="li-fan base")
            ax.plot(nodes, lifan_drop, color="#1f77b4", linewidth=2, label="li-fan earlydd")

    driver_base = rows.get(f"driver-{suffix_base}")
    driver_drop = rows.get(f"driver-{suffix_drop}")
    if driver_base is None or driver_drop is None:
        raise KeyError(
            f"Missing driver rows for plotting: "
            f"driver-{suffix_base} and/or driver-{suffix_drop}"
        )
    ax.plot(nodes, driver_base, color="#ff7f0e", linewidth=2, linestyle="--", label="driver base")
    ax.plot(nodes, driver_drop, color="#1f77b4", linewidth=2, linestyle="--", label="driver earlydd")

    if include_infp:
        driver_infp = rows.get(f"driver-CR{int(coding_rate)}-infp-{metric}")
        if driver_infp is not None:
            ax.plot(nodes, driver_infp, color="#d62728", linewidth=2, linestyle="--", label="driver infp")
        if include_lifan:
            lifan_infp = rows.get(f"lifan-CR{int(coding_rate)}-infp-{metric}")
            if lifan_infp is not None:
                ax.plot(nodes, lifan_infp, color="#d62728", linewidth=2, label="li-fan infp")

    ax.plot(nodes, nodes, color="black", linewidth=2, label="x=y")
    if title is None:
        title = f"Total decoded payloads with CR{int(coding_rate)} and {int(num_decoders)} demodulators"
    ax.set_title(title, fontsize=22)
    ax.set_xlabel("Sent packets", fontsize=22)
    ax.set_ylabel("Number of Decoded Payloads", fontsize=22)
    ax.set_xscale("log")
    if x_max is not None:
        x0 = float(x_min) if x_min is not None else float(max(1.0, float(min(nodes[nodes > 0]))))
        ax.set_xlim(x0, float(x_max))
    elif x_min is not None:
        ax.set_xlim(float(x_min), float(max(1.0, float(min(nodes[nodes > 0])))))
    if y_min is not None or y_max is not None:
        y0 = float(y_min) if y_min is not None else None
        y1 = float(y_max) if y_max is not None else None
        ax.set_ylim(y0, y1)
    ax.grid(True, which="both", linestyle="-", linewidth=0.5, alpha=0.4)
    ax.tick_params(labelsize=18)
    ax.legend(fontsize=16, loc="best")
    fig.tight_layout()

    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=220)
    plt.close(fig)
    return out_png


def runsim2plot(
    num_decoders: int,
    drop_mode: str,
    filename: str | Path,
    coding_rate: int = CR,
    metric: str = "dec_payld",
    include_lifan: bool = False,
    include_infp: bool = False,
    inf_demods: int | None = None,
    node_min: float | None = None,
    node_max: float | None = None,
    selected_nodes: list[float] | None = None,
    node_points: int = 40,
    runs_per_node: int | None = None,
    sim_time: int = simTime,
    num_ocw: int = numOCW,
    num_obw: int = numOBW,
    num_grids: int = numGrids,
    time_granularity: int = timeGranularity,
    freq_granularity: int = freqGranularity,
    link_budget_log: bool = linkBudgetLog,
    plot_enabled: bool = True,
    plot_filename: str | Path | None = None,
    x_min: float | None = None,
    x_max: float | None = None,
    y_min: float | None = None,
    y_max: float | None = None,
    title: str | None = None,
) -> tuple[Path, Path | None]:
    out_csv = runsim2csv(
        num_decoders=num_decoders,
        drop_mode=drop_mode,
        filename=filename,
        coding_rate=coding_rate,
        metric=metric,
        include_lifan=include_lifan,
        include_infp=include_infp,
        inf_demods=inf_demods,
        node_min=node_min,
        node_max=node_max,
        selected_nodes=selected_nodes,
        node_points=node_points,
        runs_per_node=runs_per_node,
        sim_time=sim_time,
        num_ocw=num_ocw,
        num_obw=num_obw,
        num_grids=num_grids,
        time_granularity=time_granularity,
        freq_granularity=freq_granularity,
        link_budget_log=link_budget_log,
    )

    if not bool(plot_enabled):
        return out_csv, None

    out_png = Path(plot_filename) if plot_filename is not None else out_csv.with_suffix(".png")
    rows = _load_runsim_csv_rows(out_csv)
    _plot_runsim_rows(
        rows=rows,
        out_png=out_png,
        num_decoders=num_decoders,
        coding_rate=coding_rate,
        metric=metric,
        drop_mode=drop_mode,
        include_lifan=include_lifan,
        include_infp=include_infp,
        x_min=x_min,
        x_max=x_max,
        y_min=y_min,
        y_max=y_max,
        title=title,
    )
    return out_csv, out_png
