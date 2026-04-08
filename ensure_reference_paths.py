import argparse
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

try:
    from tqdm import tqdm
except ImportError:  # pragma: no cover - optional dependency
    tqdm = None


LRFHSS_GIT_URLS = [
    "https://github.com/diegomm6/lr-fhss_seq-families.git",
    "git@github.com:diegomm6/lr-fhss_seq-families.git",
]
MULTI_BEAM_ZIP_URL = (
    "https://researchdata.tuwien.at/records/j31fx-wf765/files/Multi-Beam-LEO-Framework.zip?download=1"
)


def _clone_repo_if_missing(target_dir: Path, git_urls: list[str]) -> bool:
    if target_dir.exists():
        print(f"[ensure] Found existing repo: {target_dir}")
        return False

    target_dir.parent.mkdir(parents=True, exist_ok=True)
    errors = []
    for git_url in git_urls:
        print(f"[ensure] Cloning {git_url} -> {target_dir}")
        result = subprocess.run(["git", "clone", git_url, str(target_dir)], check=False)
        if result.returncode == 0:
            print(f"[ensure] Clone complete: {target_dir}")
            return True
        errors.append((git_url, result.returncode))
        print(f"[ensure] Clone failed for {git_url} (exit {result.returncode}). Trying next option...")

    attempted = ", ".join(f"{url} (exit {code})" for url, code in errors)
    raise RuntimeError(
        f"Failed to clone LR-FHSS repo into {target_dir}. "
        f"Attempts: {attempted}. See command-line output above for details."
    )


def _make_download_progress_reporter(label: str):
    last_percent = -1
    bar = None
    last_n = 0

    def _report(block_num: int, block_size: int, total_size: int):
        nonlocal last_percent, bar, last_n
        if total_size <= 0:
            return

        downloaded = min(block_num * block_size, total_size)

        if tqdm is not None:
            if bar is None:
                bar = tqdm(
                    total=total_size,
                    unit="B",
                    unit_scale=True,
                    unit_divisor=1024,
                    desc=label,
                    leave=True,
                )
            delta = downloaded - last_n
            if delta > 0:
                bar.update(delta)
                last_n = downloaded
            if downloaded >= total_size and bar is not None:
                bar.close()
                bar = None
            return

        percent = int((downloaded / total_size) * 100)
        if percent != last_percent and percent % 5 == 0:
            last_percent = percent
            print(f"[ensure] {label}: {percent}% ({downloaded}/{total_size} bytes)")
            sys.stdout.flush()

    return _report


def _download_zip_if_missing(target_dir: Path, zip_url: str) -> bool:
    if target_dir.exists():
        print(f"[ensure] Found existing directory: {target_dir}")
        return False

    target_dir.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        zip_path = tmp_path / "download.zip"
        print(f"[ensure] Downloading archive from: {zip_url}")
        urllib.request.urlretrieve(
            zip_url,
            zip_path,
            reporthook=_make_download_progress_reporter("Download progress"),
        )
        print(f"[ensure] Download complete: {zip_path}")

        print("[ensure] Extracting archive...")
        with zipfile.ZipFile(zip_path, "r") as zf:
            members = [m for m in zf.namelist() if m and not m.startswith("__MACOSX/")]
            extract_root = tmp_path / "extracted"
            extract_root.mkdir(parents=True, exist_ok=True)
            zf.extractall(extract_root)

        # Some archives contain one top-level folder; others contain loose files/folders.
        top_level_entries = [p for p in extract_root.iterdir()]
        if len(top_level_entries) == 1 and top_level_entries[0].is_dir():
            shutil.move(str(top_level_entries[0]), str(target_dir))
            print(f"[ensure] Extracted and moved to: {target_dir}")
            return True

        target_dir.mkdir(parents=True, exist_ok=True)
        for entry in top_level_entries:
            shutil.move(str(entry), str(target_dir / entry.name))
        if members:
            print(f"[ensure] Extracted contents into: {target_dir}")
            return True

    if not target_dir.exists():
        raise RuntimeError(f"Downloaded zip, but expected folder was not created: {target_dir}")
    print(f"[ensure] Extracted to: {target_dir}")
    return True


def ensure_paths(multi_beam_root: Path, lrfhss_root: Path) -> None:
    _download_zip_if_missing(multi_beam_root, MULTI_BEAM_ZIP_URL)
    _clone_repo_if_missing(lrfhss_root, LRFHSS_GIT_URLS)


def parse_args():
    integration_root = Path(__file__).resolve().parent
    snt_root = integration_root.parent

    parser = argparse.ArgumentParser(description="Ensure required external reference repositories exist.")
    parser.add_argument(
        "--multi-beam-root",
        type=Path,
        default=snt_root / "Multi-Beam-LEO-Framework",
        help="Path where Multi-Beam-LEO-Framework should exist (default: sibling folder under SNT root).",
    )
    parser.add_argument(
        "--lrfhss-root",
        type=Path,
        default=snt_root / "lr-fhss_seq-families",
        help="Path where lr-fhss_seq-families should exist (default: sibling folder under SNT root).",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    ensure_paths(args.multi_beam_root, args.lrfhss_root)


if __name__ == "__main__":
    main()
