from pathlib import Path
import sys


def _add_repo_path(repo_root: Path) -> None:
    root = repo_root.resolve()
    if not root.exists():
        raise FileNotFoundError(f"Repository path not found: {root}")
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)


def load_multi_beam_modules(multi_beam_root: Path):
    _add_repo_path(multi_beam_root)

    import channel
    import networkGeometry
    import params
    import utils

    return channel, networkGeometry, params, utils
