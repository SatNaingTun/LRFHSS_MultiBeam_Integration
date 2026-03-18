from pathlib import Path
import sys


def _add_repo_path(repo_root: Path) -> None:
    root = repo_root.resolve()
    if not root.exists():
        raise FileNotFoundError(f"Repository path not found: {root}")
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)


def load_lrfhss_components(lrfhss_root: Path):
    _add_repo_path(lrfhss_root)

    from src.models.LoRaNetwork import LoRaNetwork

    return LoRaNetwork
