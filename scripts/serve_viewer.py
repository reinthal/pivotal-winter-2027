"""Local web viewer for recorded SWE-smith trajectories.

Serves viewer/index.html plus a small JSON API over a parquet of trajectories.
By default that is subset/good_runs.parquet, the 350 verified runs shipped with
the repo (see scripts/build_subset.py); it needs no dataset download. `--raw`
browses the first `tool-*.parquet` shard of SWE-bench/SWE-smith-trajectories
from the Hugging Face cache instead. Trajectories are converted on demand with
convert_runs.convert().

    GET /                       the page
    GET /api/trajectories       list; ?q= &resolved=1|0 &status=submit|exit|rejected
                                &model= &offset= &limit=
    GET /api/trajectory?id=     one run: convert() output, plus "rejected": reason
                                (and a best-effort raw view) when convert() refuses it

Usage:
    uv run scripts/serve_viewer.py              # good runs, http://127.0.0.1:8765
    uv run scripts/serve_viewer.py --raw        # first raw shard (3013 runs)
    uv run scripts/serve_viewer.py --data some.parquet --port 9000
"""

import argparse
import glob
import json
import os
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import duckdb
from huggingface_hub import snapshot_download

sys.path.insert(0, str(Path(__file__).resolve().parent))
from convert_runs import clean_observation, convert, text_of  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "viewer" / "index.html"
GOOD_RUNS = ROOT / "subset" / "good_runs.parquet"

# Rows convert() rejects are mostly in a text function-calling format
# (<function=bash><parameter=command>...</parameter></function>, observations
# as plain user messages). Parsed only for the fallback view.
FUNC_RE = re.compile(r"<function=([\w.-]+)>(.*?)</function>", re.S)
PARAM_RE = re.compile(r"<parameter=([\w.-]+)>(.*?)</parameter>", re.S)


class Store:
    def __init__(self, data: str | None = None) -> None:
        self.con = duckdb.connect()
        if data:
            self.traj = os.path.abspath(data)
        else:
            traj_dir = snapshot_download("SWE-bench/SWE-smith-trajectories", repo_type="dataset")
            self.traj = sorted(glob.glob(os.path.join(traj_dir, "data", "tool-*.parquet")))[0]
        columns = {r[0] for r in self.con.execute(f"describe select * from '{self.traj}'").fetchall()}
        # A merged file (build_subset.py) carries the task columns itself;
        # raw shards get them from SWE-bench/SWE-smith in the HF cache.
        self.merged = {"problem_statement", "repo"} <= columns
        if not self.merged:
            task_dir = snapshot_download("SWE-bench/SWE-smith", repo_type="dataset")
            self.tasks = os.path.join(task_dir, "data", "*.parquet")
        # Cheap listing: no JSON parsing. Quotes inside message text are
        # escaped in the JSON, so this pattern only matches real role keys.
        rows = self.con.execute(f"""
            select traj_id, instance_id, model, resolved,
                   len(regexp_extract_all(messages, '"role":\\s*"assistant"')) steps
            from '{self.traj}'""").fetchall()
        self.index = [
            {"traj_id": t, "instance_id": i, "model": m, "resolved": bool(r), "steps": n,
             "status": None, "reason": None}
            for t, i, m, r, n in rows
        ]
        self.models = sorted({e["model"] for e in self.index})
        self.indexing = True
        threading.Thread(target=self._classify, daemon=True).start()

    def _select(self, where: str = "") -> str:
        if self.merged:
            return f"""
                select messages, instance_id, resolved, model, traj_id, patch,
                       problem_statement, repo
                from '{self.traj}' {where}"""
        return f"""
            select t.messages, t.instance_id, t.resolved, t.model, t.traj_id, t.patch,
                   s.problem_statement, s.repo
            from '{self.traj}' t
            left join (select instance_id, any_value(problem_statement) problem_statement,
                              any_value(repo) repo
                       from '{self.tasks}' group by 1) s using (instance_id)
            {where}"""

    def _classify(self) -> None:
        """Background pass: run convert() on every row so the list can show how
        each run ended (submit / harness exit / rejected + reason)."""
        try:
            by_id = {e["traj_id"]: e for e in self.index}
            cur = self.con.cursor()
            cur.execute(self._select())
            names = [d[0] for d in cur.description]
            while batch := cur.fetchmany(100):
                for values in batch:
                    row = dict(zip(names, values))
                    entry = by_id[row["traj_id"]]
                    try:
                        run, why = convert(row)
                    except Exception as exc:  # malformed row: list it, don't die
                        run, why = None, f"convert() raised {type(exc).__name__}: {exc}"
                    if run is None:
                        entry["status"], entry["reason"] = "rejected", why
                    elif run["gate"]["tool_call_id"] == "forced_exit":
                        entry["status"] = "exit"
                    else:
                        entry["status"] = "submit"
        finally:
            self.indexing = False

    def list(self, q: str, resolved: str, status: str, model: str, offset: int, limit: int) -> dict:
        terms = q.lower().split()
        items = [
            e for e in self.index
            if all(t in e["traj_id"].lower() for t in terms)
            and (resolved not in ("0", "1") or e["resolved"] == (resolved == "1"))
            and (not status or e["status"] == status)
            and (not model or e["model"] == model)
        ]
        return {"total": len(self.index), "matched": len(items), "indexing": self.indexing,
                "models": self.models, "offset": offset, "items": items[offset:offset + limit]}

    def get(self, traj_id: str) -> dict | None:
        cur = self.con.cursor()
        extra = ", problem_statement, repo" if self.merged else ""
        cur.execute(f"select messages, instance_id, resolved, model, traj_id, patch{extra} "
                    f"from '{self.traj}' where traj_id = ?", [traj_id])
        values = cur.fetchone()
        if values is None:
            return None
        row = dict(zip([d[0] for d in cur.description], values))
        if not self.merged:
            task = cur.execute(f"select any_value(problem_statement), any_value(repo) "
                               f"from '{self.tasks}' where instance_id = ?", [row["instance_id"]]).fetchone()
            row["problem_statement"], row["repo"] = task or (None, None)
        try:
            run, why = convert(row)
        except Exception as exc:
            run, why = None, f"convert() raised {type(exc).__name__}: {exc}"
        if run is None:
            run = raw_view(row, why)
        else:
            run["rejected"] = None
        return run


def raw_view(row: dict, reason: str) -> dict:
    """Best-effort view of a row convert() rejects, in the same shape, so the
    steps can still be browsed. Not a replay file: no gate, no diff."""
    run = {
        "traj_id": row["traj_id"], "instance_id": row["instance_id"], "model": row["model"],
        "repo": row.get("repo"), "resolved": bool(row["resolved"]),
        "task": (row.get("problem_statement") or "").replace("\r\n", "\n").strip(),
        "task_source": "swe-smith" if row.get("problem_statement") else None,
        "prompt": "", "turns": [], "results": {}, "gate": None,
        "data_notes": ["convert() rejected this row; steps below are a best-effort raw view"],
        "rejected": reason,
    }
    try:
        messages = json.loads(row["messages"])
        text_calls = False
        for i, m in enumerate(messages):
            role, text = m.get("role"), text_of(m.get("content"))
            if role == "assistant":
                calls = []
                for tc in m.get("tool_calls") or []:
                    fn = tc["function"]
                    try:
                        args = json.loads(fn["arguments"] or "{}")
                    except json.JSONDecodeError:
                        args = {"_raw": fn["arguments"]}
                    calls.append({"id": tc["id"], "name": fn["name"], "arguments": args})
                if not calls and "<function=" in text:
                    for j, f in enumerate(FUNC_RE.finditer(text)):
                        calls.append({"id": f"raw_{i}_{j}", "name": f.group(1),
                                      "arguments": dict(PARAM_RE.findall(f.group(2)))})
                    if calls:
                        text, text_calls = FUNC_RE.sub("", text).strip(), True
                run["turns"].append({"text": text, "tool_calls": calls, "observations": []})
            elif role == "tool":
                obs = clean_observation(text)
                ids = m.get("tool_call_ids") or []
                for tid in ids:
                    run["results"][tid] = obs
                if not ids and run["turns"]:
                    run["turns"][-1]["observations"].append(obs)
            elif role == "user":
                if not run["turns"]:
                    run["prompt"] = run["prompt"] or text
                else:  # text format: observations come back as user messages
                    run["turns"][-1]["observations"].append(clean_observation(text))
        if text_calls:
            run["data_notes"].append("tool calls are written as <function=…> text in this row, "
                                     "not structured tool_calls; parsed loosely for display")
    except Exception as exc:
        run["data_notes"].append(f"raw view failed: {type(exc).__name__}: {exc}")
    return run


def make_handler(store: Store):
    class Handler(BaseHTTPRequestHandler):
        def send(self, status: int, body: bytes, ctype: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def send_json(self, obj, status: int = 200) -> None:
            self.send(status, json.dumps(obj).encode(), "application/json; charset=utf-8")

        def do_GET(self) -> None:
            url = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            try:
                if url.path in ("/", "/index.html"):
                    self.send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
                elif url.path == "/api/trajectories":
                    offset = max(0, int(q.get("offset", 0)))
                    limit = min(500, max(1, int(q.get("limit", 100))))
                    self.send_json(store.list(q.get("q", ""), q.get("resolved", ""),
                                              q.get("status", ""), q.get("model", ""), offset, limit))
                elif url.path == "/api/trajectory":
                    run = store.get(q.get("id", ""))
                    if run is None:
                        self.send_json({"error": "no trajectory with that id"}, 404)
                    else:
                        self.send_json(run)
                else:
                    self.send_json({"error": "not found"}, 404)
            except ValueError as exc:
                self.send_json({"error": f"bad request: {exc}"}, 400)
            except Exception as exc:
                self.send_json({"error": f"{type(exc).__name__}: {exc}"}, 500)

        def log_message(self, fmt, *args) -> None:
            if args and str(args[1])[:1] in "45":
                sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    return Handler


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--data", help="parquet of trajectories to browse (default: subset/good_runs.parquet)")
    ap.add_argument("--raw", action="store_true",
                    help="browse the first raw tool shard from the Hugging Face cache instead")
    args = ap.parse_args()
    data = None if args.raw else args.data or str(GOOD_RUNS)
    if data and not os.path.exists(data):
        ap.error(f"{data} not found (rebuild with: uv run scripts/build_subset.py, or use --raw)")

    store = Store(data)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(store))
    print(f"{len(store.index)} trajectories from {os.path.basename(store.traj)}")
    print(f"Trajectory viewer: http://127.0.0.1:{args.port}/   (Ctrl-C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
