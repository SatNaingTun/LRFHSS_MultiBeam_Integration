import argparse
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path


LRFHSS_GIT_URL = "git@github.com:SatNaingTun/LR-FHSS_LEO.git"
MULTI_BEAM_ZIP_URL = (
    "https://researchdata.tuwien.at/records/j31fx-wf765/files/"
    "Multi-Beam-LEO-Framework.zip?download=1"
)


def _clone_repo_if_missing(target_dir: Path, git_url: str) -> bool:
    if target_dir.exists():
        return False

    target_dir.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["git", "clone", git_url, str(target_dir)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to clone {git_url} into {target_dir}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return True


def _download_zip_if_missing(target_dir: Path, zip_url: str) -> bool:
    if target_dir.exists():
        return False

    target_dir.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        zip_path = tmp_path / "download.zip"
        urllib.request.urlretrieve(zip_url, zip_path)

        with zipfile.ZipFile(zip_path, "r") as zf:
            top_entries = {
                name.split("/", 1)[0]
                for name in zf.namelist()
                if name and not name.startswith("__MACOSX/")
            }
            zf.extractall(target_dir.parent)

        if target_dir.exists():
            return True

        candidate_dirs = [target_dir.parent / entry for entry in top_entries]
        existing_dirs = [p for p in candidate_dirs if p.exists() and p.is_dir()]

        if len(existing_dirs) == 1:
            shutil.move(str(existing_dirs[0]), str(target_dir))
            return True

    if not target_dir.exists():
        raise RuntimeError(f"Downloaded zip, but expected folder was not created: {target_dir}")
    return True


def ensure_paths(multi_beam_root: Path, lrfhss_root: Path) -> None:
    _download_zip_if_missing(multi_beam_root, MULTI_BEAM_ZIP_URL)
    _clone_repo_if_missing(lrfhss_root, LRFHSS_GIT_URL)


def parse_args():
    parser = argparse.ArgumentParser(description="Ensure required external reference repositories exist.")
    parser.add_argument("--multi-beam-root", type=Path, required=True)
    parser.add_argument("--lrfhss-root", type=Path, required=True)
    return parser.parse_args()


def main():
    args = parse_args()
    ensure_paths(args.multi_beam_root, args.lrfhss_root)


if __name__ == "__main__":
    main()
