"""Merge SWE-smith trajectories with their SWE-smith task rows and keep only
the "good" runs: those whose recorded patch can be shown to belong to them.

A run is good when all of these hold:

    1. `patch` is non-empty
    2. the patch matches the trajectory (convert_runs.patch_match): every file
       it touches is mentioned in the run, and >= 90% of its added lines
       appear in the run's tool calls or tool output
    3. its instance_id has a row in SWE-bench/SWE-smith (the task)

Outputs:

    subset/good_runs.parquet  full merged rows (trajectory + task columns +
                              check columns), ~6 MB, committed; the viewer's
                              default data
    subset/good_runs.csv      small manifest: ids, labels and check columns

Task columns from SWE-smith are prefixed where they would clash: the
bug-injecting patch is `bug_patch`; the agent's patch stays `patch`.

Usage:
    uv run scripts/build_subset.py            # all cached shards of the tool split
    uv run scripts/build_subset.py --shards 1 # first shard only
"""

import argparse
import csv
import glob
import json
import os
import sys
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
from huggingface_hub import snapshot_download

sys.path.insert(0, str(Path(__file__).resolve().parent))
from convert_runs import PR_RE, convert, patch_match, text_of  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_COLUMNS = [
    "traj_id", "instance_id", "repo", "model", "resolved", "shard", "n_messages",
    "patch_files", "patch_lines", "patch_added_found", "task_matches_prompt",
    "tool_call_format", "ending", "replayable",
]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--shards", type=int, default=0, help="number of tool shards to scan (0 = all cached)")
    args = ap.parse_args()

    traj_dir = snapshot_download("SWE-bench/SWE-smith-trajectories", repo_type="dataset")
    task_dir = snapshot_download("SWE-bench/SWE-smith", repo_type="dataset")
    shards = sorted(glob.glob(os.path.join(traj_dir, "data", "tool-*.parquet")))
    if args.shards:
        shards = shards[: args.shards]
    tasks = os.path.join(task_dir, "data", "*.parquet")

    con = duckdb.connect()
    funnel = {"runs": 0, "patch non-empty": 0, "patch matches trajectory": 0, "has SWE-smith task row": 0}
    why_not = {"files not mentioned in run": 0, "files mentioned, added lines not found": 0}
    good: list[dict] = []
    for shard in shards:
        cur = con.execute(f"""
            select t.messages, t.instance_id, t.resolved, t.model, t.traj_id, t.patch,
                   s.repo, s.problem_statement, s.patch as bug_patch,
                   s.FAIL_TO_PASS, s.PASS_TO_PASS, s.image_name
            from '{shard}' t left join '{tasks}' s using (instance_id)""")
        names = [d[0] for d in cur.description]
        for values in cur.fetchall():
            row = dict(zip(names, values))
            funnel["runs"] += 1
            if not (row["patch"] or "").strip():
                continue
            funnel["patch non-empty"] += 1
            messages = json.loads(row["messages"])
            match = patch_match(row["patch"], messages)
            if not match["ok"]:
                why_not["files mentioned, added lines not found" if match["files_mentioned"]
                        else "files not mentioned in run"] += 1
                continue
            funnel["patch matches trajectory"] += 1
            if row["bug_patch"] is None:
                continue
            funnel["has SWE-smith task row"] += 1

            # Descriptive columns; none of these gate membership.
            prompt = next((text_of(m["content"]) for m in messages if m["role"] == "user"), "")
            pr = PR_RE.search(prompt)
            task = (row["problem_statement"] or "").replace("\r\n", "\n").strip()
            structured = any(m.get("tool_calls") for m in messages)
            run, reason = convert(row)
            row.update(
                shard=os.path.basename(shard),
                n_messages=len(messages),
                patch_files=row["patch"].count("diff --git "),
                patch_lines=row["patch"].count("\n"),
                patch_added_found=match["added_found"],
                # SWE-smith's problem statement vs the one the agent was actually given.
                task_matches_prompt=bool(pr) and task == pr.group(1).replace("\r\n", "\n").strip(),
                tool_call_format="structured" if structured else "text (<function=...>)",
                ending=("not convertible: " + reason) if run is None
                else "harness exit" if run["gate"]["tool_call_id"] == "forced_exit" else "submit",
                # Usable by the commit-first replay as is.
                replayable=run is not None and run["gate"]["tool_call_id"] != "forced_exit",
            )
            good.append(row)
        print(f"{os.path.basename(shard)}: {funnel['runs']} runs scanned, {len(good)} good so far", flush=True)

    (ROOT / "subset").mkdir(exist_ok=True)
    pq.write_table(pa.Table.from_pylist(good), ROOT / "subset" / "good_runs.parquet", compression="zstd")
    with open(ROOT / "subset" / "good_runs.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(good)

    print("\nfunnel")
    for name, n in funnel.items():
        print(f"  {name:28} {n:6}  ({n / funnel['runs']:.1%})")
    print("patch rejected because")
    for name, n in why_not.items():
        print(f"  {name:40} {n}")

    def share(key, value=True):
        n = sum(r[key] == value for r in good)
        return f"{n} ({n / len(good):.0%})" if good else "0"

    print(f"\ngood runs: {len(good)}")
    print(f"  resolved                     {share('resolved')}")
    print(f"  replayable in the gate       {share('replayable')}")
    print(f"  task text == agent's prompt  {share('task_matches_prompt')}")
    for key in ("model", "ending", "tool_call_format"):
        counts: dict[str, int] = {}
        for r in good:
            counts[r[key]] = counts.get(r[key], 0) + 1
        print(f"  {key}: {dict(sorted(counts.items(), key=lambda kv: -kv[1]))}")
    print(f"  instances with >1 good run   {len(good) - len({r['instance_id'] for r in good})}")
    print("\nwrote subset/good_runs.parquet and subset/good_runs.csv")


if __name__ == "__main__":
    main()
