from pathlib import Path
import sys


def add_repo_path(repo_root: Path) -> None:
    root = repo_root.resolve()
    if not root.exists():
        raise FileNotFoundError(f"Repository path not found: {root}")
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)


def bootstrap(multi_beam_root: Path, lrfhss_root: Path):
    add_repo_path(multi_beam_root)
    add_repo_path(lrfhss_root)

    import channel
    import networkGeometry
    import params
    import utils
    from src.models.LoRaNetwork import LoRaNetwork

    return channel, networkGeometry, params, utils, LoRaNetwork
