from pathlib import Path
import sys
from ensure_reference_paths import ensure_multi_beam_root


def _add_repo_path(repo_root: Path) -> None:
    root = repo_root.resolve()
    if not root.exists():
        raise FileNotFoundError(f"Repository path not found: {root}")
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)


def load_multi_beam_modules(multi_beam_root: Path):
    try:
        _add_repo_path(multi_beam_root)

        import channel
        import networkGeometry
        import params
        import utils
        import simulation

        return channel, networkGeometry, params, utils, simulation
    except ImportError as e:
        ensure_multi_beam_root(multi_beam_root)
        _add_repo_path(multi_beam_root)
        print(f"Error importing Multi-Beam-LEO-Framework modules: {e}")

        

