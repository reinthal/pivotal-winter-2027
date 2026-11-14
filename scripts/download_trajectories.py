"""Download the SWE-smith trajectories dataset from the Hugging Face Hub.

Usage:
    uv run scripts/download_trajectories.py [--out DIR]
"""

import argparse
from pathlib import Path

from huggingface_hub import snapshot_download

REPO_ID = "SWE-bench/SWE-smith-trajectories"
DEFAULT_OUT = Path(__file__).resolve().parent.parent / "data" / "swe-smith-trajectories"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="download directory")
    args = parser.parse_args()

    path = snapshot_download(repo_id=REPO_ID, repo_type="dataset", local_dir=args.out)
    print(f"Downloaded {REPO_ID} to {path}")


if __name__ == "__main__":
    main()
