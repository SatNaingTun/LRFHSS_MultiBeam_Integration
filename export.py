import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def export_metrics(records: list[dict], output_dir: Path, export_csv: bool):
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "heavy_load_metrics.json"
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)

    csv_path = None
    if export_csv and records:
        csv_path = output_dir / "heavy_load_metrics.csv"
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(records[0].keys()))
            writer.writeheader()
            writer.writerows(records)

    return json_path, csv_path


def generate_performance_plots(records: list[dict], output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)

    colors = [
        "#0072B2",
        "#E69F00",
        "#009E73",
        "#D55E00",
        "#CC79A7",
        "#56B4E9",
        "#000000",
    ]
    markers = ["o", "s", "^", "D", "P", "X", "v", "<", ">"]
    line_styles = ["-", "--", "-.", ":"]

    def get_metric_value(record: dict, metric_key: str) -> float:
        if metric_key in record:
            return float(record[metric_key])
        # Backward compatibility for older metric files.
        if metric_key == "decoded_headers" and "decoded_payloads" in record:
            return float(record["decoded_payloads"])
        if metric_key == "decoded_headers_including_payloads":
            header_only = float(record.get("decoded_headers", 0.0))
            header_payload = float(record.get("decoded_header_payloads", record.get("decoded_payloads", 0.0)))
            return header_only + header_payload
        return 0.0

    def build_series(data: list[dict], metric_key: str):
        grouped = {}
        for rec in data:
            key = (rec.get("policy_label", "Policy"), rec["mode_label"], rec["requested_demods"])
            grouped.setdefault(key, {"x": [], "y": []})
            grouped[key]["x"].append(rec["nodes"])
            grouped[key]["y"].append(get_metric_value(rec, metric_key))
        return grouped

    def plot_all_series(metric_key: str, ylabel: str, title: str, filename: str):
        grouped = build_series(records, metric_key)
        fig, ax = plt.subplots(figsize=(9, 6))
        for idx, ((policy_label, mode_label, demods), vals) in enumerate(
            sorted(grouped.items(), key=lambda t: (t[0][2], t[0][0], t[0][1]))
        ):
            x = np.array(vals["x"])
            y = np.array(vals["y"])
            order = np.argsort(x)
            ax.plot(
                x[order],
                y[order],
                linestyle=line_styles[idx % len(line_styles)],
                marker=markers[idx % len(markers)],
                linewidth=1.6,
                markersize=5,
                color=colors[idx % len(colors)],
                label=f"{policy_label} {mode_label} {demods} demods",
            )

        ax.set_xscale("symlog", linthresh=1)
        ax.set_xlabel("Number of Nodes, N (count)")
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        ax.grid(True, which="both", linestyle=":", alpha=0.5)
        ax.legend()
        fig.tight_layout()
        out_path = output_dir / filename
        fig.savefig(out_path, dpi=200)
        plt.close(fig)
        return out_path

    def plot_by_mode(metric_key: str, ylabel: str, filename: str):
        mode_names = [m for m in ["sleep", "idle", "busy"] if any(r["power_mode"] == m for r in records)]
        nrows = len(mode_names)
        fig, axes = plt.subplots(nrows=nrows, ncols=1, figsize=(10, 4 * max(1, nrows)), sharex=True)
        if nrows == 1:
            axes = [axes]

        for ax, p_mode in zip(axes, mode_names):
            sub = [r for r in records if r["power_mode"] == p_mode]
            grouped = build_series(sub, metric_key)
            for idx, ((policy_label, mode_label, demods), vals) in enumerate(
                sorted(grouped.items(), key=lambda t: (t[0][2], t[0][0], t[0][1]))
            ):
                x = np.array(vals["x"])
                y = np.array(vals["y"])
                order = np.argsort(x)
                ax.plot(
                    x[order],
                    y[order],
                    linestyle=line_styles[idx % len(line_styles)],
                    marker=markers[idx % len(markers)],
                    linewidth=1.4,
                    markersize=4.5,
                    color=colors[idx % len(colors)],
                    label=f"{policy_label} {mode_label} {demods} demods",
                )

            ax.set_xscale("symlog", linthresh=1)
            ax.set_ylabel(ylabel)
            ax.set_title(f"Power Mode: {p_mode}")
            ax.grid(True, which="both", linestyle=":", alpha=0.5)
            ax.legend(loc="best", fontsize=8)

        axes[-1].set_xlabel("Number of Nodes, N (count)")
        fig.tight_layout()
        out_path = output_dir / filename
        fig.savefig(out_path, dpi=200)
        plt.close(fig)
        return out_path

    # Primary metric: header-only decode count.
    all_plot = plot_all_series(
        metric_key="decoded_headers",
        ylabel="Decoded Headers (packets/step)",
        title="Heavy Load Test for Demodulator Constraints (Header Only)",
        filename="heavy_load_demodulator_constraints.png",
    )
    mode_plot = plot_by_mode(
        metric_key="decoded_headers",
        ylabel="Decoded Headers (packets/step)",
        filename="decoded_headers_by_power_mode.png",
    )

    # Secondary metric: fully decoded packets (header+payload).
    all_plot_header_payload = plot_all_series(
        metric_key="decoded_headers_including_payloads",
        ylabel="Decoded Headers + Payload-Decoded (packets/step)",
        title="Heavy Load Test for Demodulator Constraints (Headers Including Payload-Decoded)",
        filename="heavy_load_demodulator_constraints_header_payload.png",
    )
    mode_plot_header_payload = plot_by_mode(
        metric_key="decoded_headers_including_payloads",
        ylabel="Decoded Headers + Payload-Decoded (packets/step)",
        filename="decoded_header_payloads_by_power_mode.png",
    )

    # Power consumption plots
    power_series = {}
    for r in records:
        key = (r.get("policy_label", "Policy"), r["power_mode"], r["allocated_demods"])
        power_series.setdefault(key, {"x": [], "y": []})
        power_series[key]["x"].append(r["nodes"])
        power_series[key]["y"].append(r["power_consumption_watts"])

    fig3, ax3 = plt.subplots(figsize=(9, 6))
    for idx, ((policy_label, p_mode, demods), vals) in enumerate(
        sorted(power_series.items(), key=lambda t: (t[0][1], t[0][2], t[0][0]))
    ):
        x = np.array(vals["x"])
        y = np.array(vals["y"])
        order = np.argsort(x)
        ax3.plot(
            x[order],
            y[order],
            linestyle=line_styles[idx % len(line_styles)],
            marker=markers[idx % len(markers)],
            linewidth=1.4,
            markersize=4.5,
            color=colors[idx % len(colors)],
            label=f"{policy_label} {p_mode} {demods} demods",
        )
    ax3.set_xscale("symlog", linthresh=1)
    ax3.set_xlabel("Number of Nodes, N (count)")
    ax3.set_ylabel("Power Consumption (W)")
    ax3.set_title("Power Consumption by Power Mode and Demodulators")
    ax3.grid(True, which="both", linestyle=":", alpha=0.5)
    ax3.legend(fontsize=8)
    fig3.tight_layout()
    power_plot = output_dir / "power_consumption_by_mode.png"
    fig3.savefig(power_plot, dpi=200)
    plt.close(fig3)

    battery_x = []
    battery_y = []
    for r in records:
        battery_x.append(r["nodes"])
        battery_y.append(r["battery_percent"])

    fig4, ax4 = plt.subplots(figsize=(9, 6))
    ax4.scatter(battery_x, battery_y, c="tab:blue", s=18, label="Battery %")
    ax4.set_xscale("symlog", linthresh=1)
    ax4.set_ylabel("Battery State of Charge, SoC (%)")
    ax4.set_xlabel("Number of Nodes, N (count)")
    ax4.set_title("Battery State of Charge over Traffic Load")
    ax4.grid(True, which="both", linestyle=":", alpha=0.5)
    ax4.legend(loc="best")
    fig4.tight_layout()
    battery_plot = output_dir / "battery_percentage_over_load.png"
    fig4.savefig(battery_plot, dpi=200)
    plt.close(fig4)

    mode_names = [m for m in ["sleep", "idle", "busy"] if any(r["power_mode"] == m for r in records)]
    demod_policy_values = sorted(
        set((r.get("policy_label", "Policy"), int(r["allocated_demods"])) for r in records),
        key=lambda x: (x[1], x[0]),
    )
    fig5, axes5 = plt.subplots(nrows=len(mode_names), ncols=1, figsize=(12, 4 * max(1, len(mode_names))), sharex=True)
    if len(mode_names) == 1:
        axes5 = [axes5]

    for ax5, p_mode in zip(axes5, mode_names):
        for idx, (policy_label, demods) in enumerate(demod_policy_values):
            sub = [
                r
                for r in records
                if r["power_mode"] == p_mode
                and int(r["allocated_demods"]) == demods
                and r.get("policy_label", "Policy") == policy_label
            ]
            if not sub:
                continue
            x_vals = sorted(set(int(r["nodes"]) for r in sub))
            y_vals = []
            for x in x_vals:
                y_at_x = [float(r.get("net_power_watts", 0.0)) for r in sub if int(r["nodes"]) == x]
                y_vals.append(float(np.mean(y_at_x)))

            ax5.plot(
                x_vals,
                y_vals,
                linestyle=line_styles[idx % len(line_styles)],
                marker=markers[idx % len(markers)],
                linewidth=1.8,
                markersize=4.5,
                color=colors[idx % len(colors)],
                label=f"{policy_label} {demods} demods",
            )

        ax5.axhline(0.0, color="#444444", linewidth=1.0, linestyle="--", alpha=0.8)
        ax5.set_xscale("symlog", linthresh=1)
        ax5.set_ylabel("Net Power (W)")
        ax5.set_title(f"Power Mode: {p_mode}")
        ax5.grid(True, which="both", linestyle=":", alpha=0.5)
        ax5.legend(loc="best", fontsize=8)

    axes5[-1].set_xlabel("Number of Nodes, N (count)")
    fig5.suptitle("Net Power (Charging - Discharging) by Power Mode and Demodulators")
    fig5.tight_layout(rect=(0, 0, 1, 0.97))
    net_power_plot = output_dir / "net_power_by_mode.png"
    fig5.savefig(net_power_plot, dpi=200)
    plt.close(fig5)

    throughput_plot = plot_all_series(
        metric_key="throughput_bps",
        ylabel="Throughput (bps)",
        title="Throughput versus Traffic Load",
        filename="throughput_bps.png",
    )
    energy_per_bit_plot = plot_all_series(
        metric_key="energy_per_decoded_bit_j",
        ylabel="Energy per Decoded Bit (J/bit)",
        title="Energy per Decoded Bit versus Traffic Load",
        filename="energy_per_decoded_bit.png",
    )
    decoding_efficiency_plot = plot_all_series(
        metric_key="decoding_efficiency",
        ylabel="Decoding Efficiency (decoded/tracked)",
        title="Decoding Efficiency versus Traffic Load",
        filename="decoding_efficiency.png",
    )

    return {
        "all_series": all_plot,
        "by_power_mode": mode_plot,
        "all_series_header_payload": all_plot_header_payload,
        "by_power_mode_header_payload": mode_plot_header_payload,
        "power_consumption": power_plot,
        "battery_percentage": battery_plot,
        "net_power_by_mode": net_power_plot,
        "throughput_bps": throughput_plot,
        "energy_per_decoded_bit": energy_per_bit_plot,
        "decoding_efficiency": decoding_efficiency_plot,
    }
