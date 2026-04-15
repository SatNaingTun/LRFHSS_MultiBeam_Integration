import csv
import random
from pathlib import Path

import numpy as np

from LoRaNetwork import LoRaNetwork
from base.base import (
    CR,
    freqGranularity,
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
) -> float:
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

    local_runs = max(1, int(runs if runs_per_node is None else runs_per_node))
    vals: list[float] = []
    run_iter = range(local_runs)
    if tqdm is not None and local_runs > 1:
        run_iter = tqdm(run_iter, desc=f"Running simulations for {local_runs} runs", leave=False)
    for r in run_iter:
        random.seed(2 * r)
        network.get_predecoded_data()
        network.run(power, dynamic)
        vals.append(_metric_from_network(network, metric=metric))
        network.restart()
    return float(np.mean(np.array(vals, dtype=float)))

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
) -> Path:
    nodes = _resolve_nodes(
        node_min=node_min,
        node_max=node_max,
        selected_nodes=selected_nodes,
        node_points=node_points,
    )
    families = ["driver"] + (["lifan"] if include_lifan else [])

    rows: list[tuple[str, list[float]]] = []
    node_vals = [float(v) for v in nodes]
    rows.append(("nodes", node_vals))
    rows.append(("x_equals_y", node_vals))

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
            base_vals.append(
                run_sim(
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
                )
            )
            dd_vals.append(
                run_sim(
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
                )
            )
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
    return out
