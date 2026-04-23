from __future__ import annotations

import sys
from pathlib import Path

from modules import satellite_simulator


def main() -> int:
    root = Path(__file__).resolve().parent

    default_args = [
        "--steps",
        "1",
        "--infp",
        "on",
        "--include-elev",
        "on",
        "--output-dir",
        str(root / "results" / "one_location"),
        "--one_pos_output_dir",
        str(root / "results" / "one_location"/ "one_pos"),
    ]

    # User-supplied args are appended so they can override defaults.
    sys.argv = [sys.argv[0]] + default_args + sys.argv[1:]
    return int(satellite_simulator.main())


if __name__ == "__main__":
    raise SystemExit(main())
