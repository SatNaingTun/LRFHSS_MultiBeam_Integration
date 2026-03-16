import argparse
import importlib.metadata
import subprocess
import sys
from pathlib import Path


def parse_args():
    integration_root = Path(__file__).resolve().parent
    snt_root = integration_root.parent

    parser = argparse.ArgumentParser(
        description=(
            "Run full workflow: orbit -> visibility -> nodes -> LR-FHSS packets -> visibility check -> "
            "power mode -> transmit -> collisions -> demods -> baseline decode -> metrics -> plots"
        )
    )
    parser.add_argument("--multi-beam-root", type=Path, default=snt_root / "Multi-Beam-LEO-Framework")
    parser.add_argument("--lrfhss-root", type=Path, default=snt_root / "LR-FHSS_LEO")
    parser.add_argument("--output-dir", type=Path, default=integration_root / "results" / "heavy_load")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--node-min", type=int, default=10)
    parser.add_argument("--node-max", type=int, default=1500)
    parser.add_argument("--node-points", type=int, default=14)
    parser.add_argument(
        "--nodes",
        type=int,
        nargs="+",
        default=[0, 1, 5, 10, 20, 50, 100, 150, 200, 300, 500, 800, 1000, 1200, 1500],
        help="Explicit node list; overrides --node-min/--node-max/--node-points.",
    )
    parser.add_argument("--demods", type=int, nargs="+", default=[10, 100, 1000])
    return parser.parse_args()


def _parse_requirement_names(requirements_path: Path):
    names = []
    for raw_line in requirements_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        # Keep only the package name before common version/env markers.
        for marker in ("==", ">=", "<=", "~=", "!=", ">", "<", ";", "["):
            if marker in line:
                line = line.split(marker, 1)[0].strip()
        if line:
            names.append(line)
    return names


def ensure_python_dependencies():
    integration_root = Path(__file__).resolve().parent
    requirements_path = integration_root / "requirements.txt"

    if not requirements_path.exists():
        print("[deps] requirements.txt not found. Skipping dependency check.")
        return

    packages = _parse_requirement_names(requirements_path)
    missing = []
    for package in packages:
        try:
            importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            missing.append(package)

    if not missing:
        print("[deps] All Python dependencies are already installed.")
        return

    print(f"[deps] Missing dependencies detected: {', '.join(missing)}")
    print("[deps] Installing from requirements.txt (download progress will be shown below)...")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(requirements_path)],
        check=True,
    )
    print("[deps] Dependency installation complete.")


def main():
    args = parse_args()
    ensure_python_dependencies()

    from workflow import run_workflow

    if (not args.multi_beam_root.exists()) or (not args.lrfhss_root.exists()):
        ensure_script = Path(__file__).resolve().parent / "ensure_reference_paths.py"
        subprocess.run(
            [
                sys.executable,
                str(ensure_script),
                "--multi-beam-root",
                str(args.multi_beam_root),
                "--lrfhss-root",
                str(args.lrfhss_root),
            ],
            check=True,
        )

    run_workflow(
        multi_beam_root=args.multi_beam_root,
        lrfhss_root=args.lrfhss_root,
        output_dir=args.output_dir,
        seed=args.seed,
        node_min=args.node_min,
        node_max=args.node_max,
        node_points=args.node_points,
        demodulator_options=args.demods,
        nodes_list=args.nodes,
    )


if __name__ == "__main__":
    main()
