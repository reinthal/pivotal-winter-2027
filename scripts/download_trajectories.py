"""Download SWE-smith trajectories and the task instances behind them.

Both datasets go into the standard Hugging Face cache (~/.cache/huggingface/hub,
or $HF_HOME), so reruns are no-ops and `datasets.load_dataset(repo_id)` or
`snapshot_download(repo_id, repo_type="dataset")` resolve locally afterwards.

Usage:
    uv run scripts/download_trajectories.py
"""

from huggingface_hub import snapshot_download

REPO_IDS = [
    "SWE-bench/SWE-smith-trajectories",  # agent runs
    "SWE-bench/SWE-smith",  # task instances the runs were made on
]


def main() -> None:
    for repo_id in REPO_IDS:
        path = snapshot_download(repo_id=repo_id, repo_type="dataset")
        print(f"{repo_id} -> {path}")


if __name__ == "__main__":
    main()
