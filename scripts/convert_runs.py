"""Convert recorded SWE-smith trajectories into replay files for the pi
`commit-first` extension.

One output file per run: replays/<traj_id>.json

    {
      "traj_id", "instance_id", "model", "repo",
      "resolved":      ground truth (never shown to the reviewer, only logged),
      "task":          problem statement shown to the reviewer,
      "task_source":   "swe-smith" | "trajectory",
      "prompt":        first user message (what the agent was actually told),
      "turns":         [{"text", "tool_calls": [{"id", "name", "arguments"}]}],
      "results":       {tool_call_id: observation text},
      "gate":          {"tool_call_id", "diff", "diff_source"},
      "data_notes":    [str]   problems found in this row
    }

The extension replays `turns` as model output and `results` as tool output, so
pi emits its normal tool_call / tool_result events for a run that already
happened. The gate fires on `gate.tool_call_id`.

Usage:
    uv run scripts/convert_runs.py                 # balanced sample of 4
    uv run scripts/convert_runs.py --n 6 --seed 1
    uv run scripts/convert_runs.py --traj-id <id>  # one specific run
    uv run scripts/convert_runs.py --stats         # data problems only
"""

import argparse
import glob
import json
import os
import re
from pathlib import Path

import duckdb
from huggingface_hub import snapshot_download

OUT_DIR = Path(__file__).resolve().parent.parent / "replays"
DIFF_RE = re.compile(r"<diff>\n(.*?)\n?</diff>", re.S)
# Share of a patch's added lines that must appear in the trajectory.
PATCH_MATCH_MIN = 0.9
PR_RE = re.compile(r"<pr_description>\n?(.*?)\n?</pr_description>", re.S)


def text_of(content) -> str:
    """Message content is a plain string for assistant turns and a list of
    {"type": "text", "text": ...} blocks for user/tool turns."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") for b in content if isinstance(b, dict))


def clean_observation(text: str) -> str:
    text = text.replace("\r\n", "\n")
    return text.removeprefix("OBSERVATION:\n")


def patch_match(patch: str, messages: list[dict]) -> dict:
    """Does the dataset's `patch` belong to this trajectory?

    The `patch` column is misaligned in most rows: it touches files the run
    never mentions (an apispec run carries a flashtext patch). Two checks:

    files_mentioned  every file in the patch appears somewhere in the run
    added_found      share of the patch's added lines that appear in the run's
                     tool-call arguments or tool output (the agent has to have
                     written them, or seen them in the submit review diff)
    """
    patch = (patch or "").replace("\r\n", "\n")
    if not patch.strip():
        return {"empty": True, "files_mentioned": False, "added_found": 0.0, "ok": False}
    parts = []
    for m in messages:
        parts.append(text_of(m.get("content")))
        for tc in m.get("tool_calls") or []:
            try:
                args = json.loads(tc["function"]["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {"_raw": tc["function"]["arguments"]}
            parts.extend(str(v) for v in args.values()) if isinstance(args, dict) else parts.append(str(args))
    corpus = "\n".join(parts).replace("\r\n", "\n")
    files = re.findall(r"^diff --git a/(\S+)", patch, re.M)
    added = [l[1:].strip() for l in patch.split("\n") if l.startswith("+") and not l.startswith("+++")]
    added = [l for l in added if len(l) > 3]
    found = sum(l in corpus for l in added) / len(added) if added else 0.0
    mentioned = bool(files) and all(f in corpus for f in files)
    return {"empty": False, "files_mentioned": mentioned, "added_found": round(found, 3),
            "ok": mentioned and found >= PATCH_MATCH_MIN}


def pick_diff(row, turns, results, submit_ids, notes) -> tuple[str, str]:
    """Choose the code change to show, in order of preference:

    1. the dataset patch, if patch_match() verifies it against the trajectory
       (it is the final, post-cleanup patch),
    2. the diff the submit tool printed for the agent's own review,
    3. the agent's edit calls, rendered as a pseudo-diff.
    """
    if patch_match(row["patch"], json.loads(row["messages"]))["ok"]:
        return row["patch"].replace("\r\n", "\n"), "dataset patch (verified against trajectory)"

    for sid in reversed(submit_ids):
        found = DIFF_RE.search(results.get(sid, ""))
        if found and found.group(1).strip():
            notes.append("dataset patch is not this run's; diff is the pre-cleanup review diff, may include scratch scripts")
            # Edits to existing files first, files the agent created last.
            parts = re.split(r"(?m)^(?=diff --git )", found.group(1))
            parts.sort(key=lambda part: "\nnew file mode" in part)
            return "".join(p if p.endswith("\n") else p + "\n" for p in parts if p), "submit review output"

    chunks = []
    for turn in turns:
        for call in turn["tool_calls"]:
            a = call["arguments"]
            if call["name"] != "str_replace_editor" or a.get("command") not in ("str_replace", "insert", "create"):
                continue
            minus = a.get("old_str") or ""
            plus = a.get("new_str") or a.get("file_text") or ""
            if "Error" in results.get(call["id"], "")[:200] and "has been edited" not in results.get(call["id"], ""):
                continue  # edit was rejected by the tool
            where = f" (insert after line {a.get('insert_line')})" if a.get("command") == "insert" else ""
            body = [f"-{l}" for l in minus.split("\n") if minus] + [f"+{l}" for l in plus.split("\n") if plus]
            chunks.append(f"--- {a.get('command')} {a.get('path')}{where}\n" + "\n".join(body))
    if chunks:
        notes.append("no diff recorded; code change rebuilt from the agent's edit calls, in order")
    return "\n".join(chunks), "reconstructed from edit calls"


def convert(row: dict) -> tuple[dict | None, str | None]:
    """Return (run, None) or (None, reason it cannot be replayed)."""
    notes: list[str] = []
    messages = json.loads(row["messages"])

    user = next((m for m in messages if m["role"] == "user"), None)
    if user is None:
        return None, "no user message"
    prompt = text_of(user["content"])

    turns, results, submit_ids = [], {}, []
    for m in messages:
        if m["role"] == "assistant":
            calls = []
            for tc in m.get("tool_calls") or []:
                fn = tc["function"]
                try:
                    args = json.loads(fn["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {"_raw": fn["arguments"]}
                    notes.append("unparseable tool arguments")
                calls.append({"id": tc["id"], "name": fn["name"], "arguments": args})
                if fn["name"] == "submit":
                    submit_ids.append(tc["id"])
            turns.append({"text": text_of(m["content"]), "tool_calls": calls})
        elif m["role"] == "tool":
            obs = clean_observation(text_of(m["content"]))
            for tid in m.get("tool_call_ids") or []:
                results[tid] = obs

    if not submit_ids:
        # 37% of runs never call submit: the harness stops the agent ("Exit due
        # to cost limit", context overflow, ...) and auto-submits whatever diff
        # exists. To gate those too, turn the harness exit line into a
        # synthetic submit event. The exit line is harness text, not an agent
        # summary, so these runs have nothing to reveal in phase two.
        last = turns[-1] if turns else None
        if not (last and not last["tool_calls"] and last["text"].startswith("Exit due to")):
            return None, "no submit call and no harness exit"
        reason = last["text"].split(":")[0][:80]
        last["tool_calls"] = [{"id": "forced_exit", "name": "submit",
                               "arguments": {"forced_exit": reason}}]
        last["text"] = ""
        submit_ids.append("forced_exit")
        notes.append(f"no submit call; synthetic submit from harness exit ({reason})")

    # SWE-agent's submit is two-step: the first call returns a review checklist
    # plus the diff, the last call is the one that actually ends the run. Gate
    # on the last one, when the diff is final.
    gate_id = submit_ids[-1]
    if len(submit_ids) > 2:
        notes.append(f"{len(submit_ids)} submit calls")
    # (The final submit never has a recorded observation: the run ends there.)

    diff, diff_source = pick_diff(row, turns, results, submit_ids, notes)
    if not diff.strip():
        return None, "no code change recoverable"

    task, task_source = row.get("problem_statement"), "swe-smith"
    if not task or not task.strip():
        found = PR_RE.search(prompt)
        if not found:
            return None, "no task description"
        task, task_source = found.group(1), "trajectory"
        notes.append("no SWE-smith row for instance; task taken from agent prompt")

    return {
        "traj_id": row["traj_id"],
        "instance_id": row["instance_id"],
        "model": row["model"],
        "repo": row.get("repo"),
        "resolved": bool(row["resolved"]),
        "task": task.replace("\r\n", "\n").strip(),
        "task_source": task_source,
        "prompt": prompt,
        "turns": turns,
        "results": results,
        "gate": {"tool_call_id": gate_id, "diff": diff, "diff_source": diff_source},
        "data_notes": notes,
    }, None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--n", type=int, default=4, help="runs to sample (half resolved, half not)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--traj-id", action="append", help="convert these runs instead of sampling")
    ap.add_argument("--max-diff-lines", type=int, default=120, help="sample only reviewable diffs")
    ap.add_argument("--include-forced", action="store_true",
                    help="also sample runs the harness stopped without a submit call")
    ap.add_argument("--stats", action="store_true", help="print data problems and exit")
    args = ap.parse_args()

    traj_dir = snapshot_download("SWE-bench/SWE-smith-trajectories", repo_type="dataset")
    task_dir = snapshot_download("SWE-bench/SWE-smith", repo_type="dataset")
    # One shard of the `tool` split is enough (task brief: one data file).
    traj = sorted(glob.glob(os.path.join(traj_dir, "data", "tool-*.parquet")))[0]
    tasks = os.path.join(task_dir, "data", "*.parquet")
    base = f"""
        from '{traj}' t
        left join (select instance_id, any_value(problem_statement) problem_statement,
                          any_value(repo) repo
                   from '{tasks}' group by 1) s using (instance_id)
    """
    con = duckdb.connect()

    if args.stats:
        rel = con.sql(f"""
            select count(*) runs,
                   count(distinct instance_id) instances,
                   count(*) - count(distinct traj_id) dup_traj_ids,
                   count(*) filter (resolved) resolved,
                   count(*) filter (coalesce(t.patch,'') = '') empty_patch,
                   count(*) filter (resolved and coalesce(t.patch,'') = '') resolved_but_empty_patch,
                   count(*) filter (coalesce(problem_statement,'') = '') no_problem_statement
            {base}""")
        for name, value in zip(rel.columns, rel.fetchall()[0]):
            print(f"{name:26} {value}")
        # Submit-call counts need the parsed messages.
        counts: dict[int, int] = {}
        foreign = 0
        for m, patch in con.execute(f"select messages, patch from '{traj}'").fetchall():
            files = re.findall(r"^diff --git a/(\S+)", patch or "", re.M)
            foreign += bool(files) and not all(f in m for f in files)
            n = sum(tc["function"]["name"] == "submit"
                    for msg in json.loads(m) for tc in msg.get("tool_calls") or [])
            counts[n] = counts.get(n, 0) + 1
        print(f"{'patch_from_another_row':26} {foreign}  (patch touches files the run never mentions)")
        print("submit calls per run:", dict(sorted(counts.items())))
        return

    cols = "t.messages, t.instance_id, t.resolved, t.model, t.traj_id, t.patch, s.problem_statement, s.repo"
    if args.traj_id:
        ids = ", ".join("'" + i.replace("'", "''") + "'" for i in args.traj_id)
        cur = con.execute(f"select {cols} {base} where t.traj_id in ({ids})")
    else:
        # Deterministic shuffle; over-fetch so unusable rows can be skipped.
        cur = con.execute(f"select {cols} {base} order by hash(t.traj_id || '{args.seed}') limit 400")
    names = [d[0] for d in cur.description]
    rows = [dict(zip(names, r)) for r in cur.fetchall()]

    want = {True: (args.n + 1) // 2, False: args.n // 2}
    OUT_DIR.mkdir(exist_ok=True)
    skipped: dict[str, int] = {}
    written = []
    for row in rows:
        run, why = convert(row)
        if run is None:
            skipped[why] = skipped.get(why, 0) + 1
            continue
        if not args.traj_id:
            if want[run["resolved"]] == 0:
                continue
            if run["gate"]["tool_call_id"] == "forced_exit" and not args.include_forced:
                skipped["harness exit, no submit"] = skipped.get("harness exit, no submit", 0) + 1
                continue
            if run["gate"]["diff"].count("\n") > args.max_diff_lines:
                skipped["diff too long for demo"] = skipped.get("diff too long for demo", 0) + 1
                continue
            want[run["resolved"]] -= 1
        path = OUT_DIR / f"{run['traj_id']}.json"
        path.write_text(json.dumps(run, indent=1))
        written.append(path)
        print(f"{path.relative_to(OUT_DIR.parent)}  turns={len(run['turns'])} "
              f"diff={run['gate']['diff_source']} notes={run['data_notes']}")
        if not args.traj_id and not any(want.values()):
            break
    print(f"wrote {len(written)} runs; skipped while scanning: {skipped}")


if __name__ == "__main__":
    main()
