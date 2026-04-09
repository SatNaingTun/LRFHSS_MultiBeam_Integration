from pathlib import Path
import sys
from ensure_reference_paths import ensure_lrfhss_root


def _add_repo_path(repo_root: Path) -> None:
    root = repo_root.resolve()
    if not root.exists():
        raise FileNotFoundError(f"Repository path not found: {root}")
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)


def load_lrfhss_components(lrfhss_root: Path):
    try:
        _add_repo_path(lrfhss_root)

        from src.models.LoRaNetwork import LoRaNetwork

        return LoRaNetwork
    except ImportError as e:
        ensure_lrfhss_root(lrfhss_root)
        _add_repo_path(lrfhss_root)
        print(f"Error importing LRFHSS components: {e}")
       
