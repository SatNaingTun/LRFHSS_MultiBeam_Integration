#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
import re
import shutil

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


@dataclass
class ComparisonSeries:
    nodes: np.ndarray
    driver_base: np.ndarray
    driver_earlydd: np.ndarray
    lifan_base: np.ndarray | None = None
    lifan_earlydd: np.ndarray | None = None
    driver_infp: np.ndarray | None = None
    lifan_infp: np.ndarray | None = None
    demods: int = 100
    coding_rate: int = 1
    metric: str = "dec_payld"


def load_row_csv(path: Path) -> dict[str, np.ndarray]:
    data: dict[str, np.ndarray] = {}
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            key = str(row[0]).strip()
            vals: list[float] = []
            for token in row[1:]:
                tok = str(token).strip()
                if not tok:
                    continue
                try:
                    vals.append(float(tok))
                except ValueError:
                    vals.append(np.nan)
            if vals:
                data[key] = np.array(vals, dtype=float)
    return data


def list_available_demod_counts(reference_csv: Path, coding_rate: int = 1, family: str = "driver") -> list[int]:
    rows = load_row_csv(reference_csv)
    pattern = re.compile(rf"^{re.escape(family)}-CR{int(coding_rate)}-(\d+)p-")
    demods: set[int] = set()
    for key in rows:
        m = pattern.match(key)
        if m:
            demods.add(int(m.group(1)))
    return sorted(demods)


def _slice_common_length(rows: dict[str, np.ndarray], keys: list[str]) -> int:
    common_len = min(len(rows[k]) for k in keys)
    if common_len <= 0:
        raise ValueError(f"No numeric points found in required rows: {keys}")
    return common_len


def _filter_nodes(
    nodes: np.ndarray,
    values: dict[str, np.ndarray],
    node_min: float | None = None,
    node_max: float | None = None,
    selected_nodes: list[float] | None = None,
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    mask = np.ones(nodes.shape[0], dtype=bool)
    if node_min is not None:
        mask &= nodes >= float(node_min)
    if node_max is not None:
        mask &= nodes <= float(node_max)
    if selected_nodes:
        selected = np.array([float(v) for v in selected_nodes], dtype=float)
        mask &= np.isin(nodes, selected)
    if not np.any(mask):
        raise ValueError("Node filter removed all points. Adjust node_min/node_max/nodes.")

    filtered = {k: v[mask] for k, v in values.items()}
    return nodes[mask], filtered


def build_comparison_series(
    reference_csv: Path,
    demods: int = 100,
    coding_rate: int = 1,
    metric: str = "dec_payld",
    drop_mode: str = "rlydd",
    include_lifan: bool = True,
    include_infp: bool = False,
    node_min: float | None = None,
    node_max: float | None = None,
    selected_nodes: list[float] | None = None,
) -> ComparisonSeries:
    rows = load_row_csv(reference_csv)
    suffix_base = f"CR{int(coding_rate)}-{int(demods)}p-{metric}-base"
    suffix_drop = f"CR{int(coding_rate)}-{int(demods)}p-{metric}-{drop_mode}"

    required = [
        "nodes",
        f"driver-{suffix_base}",
        f"driver-{suffix_drop}",
    ]
    if include_lifan:
        required.extend(
            [
                f"lifan-{suffix_base}",
                f"lifan-{suffix_drop}",
            ]
        )
    if include_infp:
        required.append(f"driver-CR{int(coding_rate)}-infp-{metric}")
        if include_lifan:
            required.append(f"lifan-CR{int(coding_rate)}-infp-{metric}")

    missing = [k for k in required if k not in rows]
    if missing and drop_mode != "rlydd":
        fallback_required = [k.replace(f"-{drop_mode}", "-rlydd") for k in required]
        fallback_missing = [k for k in fallback_required if k not in rows]
        if not fallback_missing:
            required = fallback_required
            suffix_drop = suffix_drop.replace(f"-{drop_mode}", "-rlydd")
            print(f"[lrfhss] Requested drop_mode='{drop_mode}' not found; using 'rlydd' from reference CSV.")
            missing = []
    if missing:
        available = list_available_demod_counts(reference_csv, coding_rate=coding_rate, family="driver")
        raise KeyError(
            f"Missing required rows in {reference_csv}: {missing}. "
            f"Available driver demods for CR{coding_rate}: {available}"
        )

    common_len = _slice_common_length(rows, required)

    values: dict[str, np.ndarray] = {
        "driver_base": rows[f"driver-{suffix_base}"][:common_len],
        "driver_earlydd": rows[f"driver-{suffix_drop}"][:common_len],
    }
    if include_lifan:
        values["lifan_base"] = rows[f"lifan-{suffix_base}"][:common_len]
        values["lifan_earlydd"] = rows[f"lifan-{suffix_drop}"][:common_len]
    if include_infp:
        values["driver_infp"] = rows[f"driver-CR{int(coding_rate)}-infp-{metric}"][:common_len]
        if include_lifan:
            values["lifan_infp"] = rows[f"lifan-CR{int(coding_rate)}-infp-{metric}"][:common_len]

    nodes = rows["nodes"][:common_len]
    nodes, filtered = _filter_nodes(
        nodes,
        values,
        node_min=node_min,
        node_max=node_max,
        selected_nodes=selected_nodes,
    )

    return ComparisonSeries(
        nodes=nodes,
        driver_base=filtered["driver_base"],
        driver_earlydd=filtered["driver_earlydd"],
        lifan_base=filtered.get("lifan_base"),
        lifan_earlydd=filtered.get("lifan_earlydd"),
        driver_infp=filtered.get("driver_infp"),
        lifan_infp=filtered.get("lifan_infp"),
        demods=int(demods),
        coding_rate=int(coding_rate),
        metric=metric,
    )


def plot_comparison_curves(
    series: ComparisonSeries,
    out_png: Path,
    out_pdf: Path | None = None,
    y_max: float | None = None,
    x_min: float | None = None,
    x_max: float | None = None,
    include_lifan: bool = True,
    include_infp: bool = False,
    title: str | None = None,
) -> None:
    fig, ax = plt.subplots(figsize=(10, 8))

    if include_lifan and series.lifan_base is not None and series.lifan_earlydd is not None:
        ax.plot(series.nodes, series.lifan_base, color="#ff7f0e", linewidth=2, label="li-fan base")
        ax.plot(series.nodes, series.lifan_earlydd, color="#1f77b4", linewidth=2, label="li-fan earlydd")
    if include_infp and series.driver_infp is not None:
        ax.plot(series.nodes, series.driver_infp, color="#d62728", linewidth=2, linestyle="--", label="driver infp")
    if include_infp and include_lifan and series.lifan_infp is not None:
        ax.plot(series.nodes, series.lifan_infp, color="#d62728", linewidth=2, label="li-fan infp")

    ax.plot(series.nodes, series.driver_base, color="#ff7f0e", linewidth=2, linestyle="--", label="driver base")
    ax.plot(series.nodes, series.driver_earlydd, color="#1f77b4", linewidth=2, linestyle="--", label="driver earlydd")
    ax.plot(series.nodes, series.nodes, color="black", linewidth=2, label="x=y")

    if title is None:
        title = f"Total decoded payloads with CR{series.coding_rate} and {series.demods} demodulators"

    ax.set_title(title, fontsize=18)
    ax.set_xlabel("Sent packets", fontsize=18)
    ax.set_ylabel("Number of Decoded Payloads", fontsize=18)
    ax.set_xscale("log")
    if x_min is not None and x_max is not None:
        ax.set_xlim(float(x_min), float(x_max))
    if y_max is not None:
        ax.set_ylim(0, float(y_max))
    ax.grid(True, which="both", linestyle="-", linewidth=0.5, alpha=0.4)
    ax.tick_params(labelsize=14)
    ax.legend(fontsize=16, loc="lower center")
    fig.tight_layout()

    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=220)
    if out_pdf is not None:
        out_pdf.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out_pdf)
    plt.close(fig)


def run_reference_comparison(
    reference_csv: Path,
    output_dir: Path,
    demods: int = 100,
    coding_rate: int = 1,
    metric: str = "dec_payld",
    drop_mode: str = "rlydd",
    y_max: float | None = None,
    x_min: float | None = None,
    x_max: float | None = None,
    include_lifan: bool = True,
    include_infp: bool = False,
    node_min: float | None = 100.0,
    node_max: float | None = 10000.0,
    selected_nodes: list[float] | None = None,
    export_pdf: bool = False,
) -> tuple[Path, Path]:
    series = build_comparison_series(
        reference_csv=reference_csv,
        demods=demods,
        coding_rate=coding_rate,
        metric=metric,
        drop_mode=drop_mode,
        include_lifan=include_lifan,
        include_infp=include_infp,
        node_min=node_min,
        node_max=node_max,
        selected_nodes=selected_nodes,
    )
    base_stem = f"lrfhss_demod_{int(demods)}"
    name_parts = [base_stem]
    if metric == "dec_pckts":
        name_parts.append("packet_only")
    if include_infp:
        name_parts.append("infp")
    if drop_mode in {"hdrdd", "headerdrop"}:
        name_parts.append("headerdrop")
    tagged_stem = "_".join(name_parts)
    out_png = output_dir / f"{base_stem}.png"
    out_pdf = output_dir / f"{base_stem}.pdf"
    plot_comparison_curves(
        series=series,
        out_png=out_png,
        out_pdf=out_pdf if export_pdf else None,
        y_max=y_max,
        x_min=x_min,
        x_max=x_max,
        include_lifan=include_lifan,
        include_infp=include_infp,
    )
    if tagged_stem != base_stem:
        tagged_png = output_dir / f"{tagged_stem}.png"
        shutil.copyfile(out_png, tagged_png)
        if export_pdf:
            tagged_pdf = output_dir / f"{tagged_stem}.pdf"
            shutil.copyfile(out_pdf, tagged_pdf)
    return out_png, out_pdf


def parse_args() -> argparse.Namespace:
    integration_root = Path(__file__).resolve().parent
    snt_root = integration_root.parent
    parser = argparse.ArgumentParser(
        description="Reusable LR-FHSS communication replication with configurable demods and node range."
    )
    parser.add_argument(
        "--reference-csv",
        type=Path,
        default=snt_root / "lr-fhss_seq-families" / "headerResults" / "data-25dc-cr1.csv",
    )
    parser.add_argument("--output-dir", type=Path, default=integration_root / "results" / "lrfhss_compare")
    parser.add_argument("--demods", type=int, default=100)
    parser.add_argument("--coding-rate", type=int, default=1)
    parser.add_argument("--metric", type=str, default="dec_payld")
    parser.add_argument(
        "--drop-mode",
        type=str,
        default="rlydd",
        choices=["rlydd", "headerdrop", "hdrdd"],
        help="Drop-policy curve key to compare against base. headerdrop maps to hdrdd key if available.",
    )
    parser.add_argument(
        "--packet-only",
        action="store_true",
        help="Use packet metric (dec_pckts) instead of payload metric (dec_payld).",
    )
    parser.add_argument("--x-min", type=float, default=None, help="Optional fixed X-axis min.")
    parser.add_argument("--x-max", type=float, default=None, help="Optional fixed X-axis max.")
    parser.add_argument("--node-min", type=float, default=100.0)
    parser.add_argument("--node-max", type=float, default=10000.0)
    parser.add_argument("--nodes", type=float, nargs="+", default=None)
    parser.add_argument("--y-max", type=float, default=None, help="Optional fixed Y-axis max; default is auto.")
    parser.add_argument(
        "--include-lifan",
        action="store_true",
        help="Also include li-fan base/earlydd curves (default is driver-only).",
    )
    parser.add_argument(
        "--include-infp",
        action="store_true",
        help="Also include infinite-demod (infp) curve from reference data.",
    )
    parser.add_argument(
        "--list-demods",
        action="store_true",
        help="Print available demod counts for selected coding rate and exit.",
    )
    parser.add_argument(
        "--export-pdf",
        action="store_true",
        help="Also export PDF (default is PNG only).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.list_demods:
        available = list_available_demod_counts(args.reference_csv, coding_rate=args.coding_rate, family="driver")
        print(f"Available driver demods for CR{int(args.coding_rate)}: {available}")
        return

    metric = "dec_pckts" if args.packet_only else args.metric
    drop_mode = "hdrdd" if args.drop_mode == "headerdrop" else args.drop_mode

    out_png, out_pdf = run_reference_comparison(
        reference_csv=args.reference_csv,
        output_dir=args.output_dir,
        demods=args.demods,
        coding_rate=args.coding_rate,
        metric=metric,
        drop_mode=drop_mode,
        y_max=args.y_max,
        x_min=args.x_min,
        x_max=args.x_max,
        include_lifan=args.include_lifan,
        include_infp=args.include_infp,
        node_min=args.node_min,
        node_max=args.node_max,
        selected_nodes=args.nodes,
        export_pdf=args.export_pdf,
    )
    print(f"Saved plot: {out_png.resolve()}")
    if args.export_pdf:
        print(f"Saved plot: {out_pdf.resolve()}")


if __name__ == "__main__":
    main()
