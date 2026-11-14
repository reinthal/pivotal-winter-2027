#!/usr/bin/env bash
# Replay one recorded run in pi with the commit-first review gate.
#
#   scripts/replay.sh                        a random replayable run from the good-runs subset
#   scripts/replay.sh <traj_id>              that run (converted on the fly if needed)
#   scripts/replay.sh replays/<traj_id>.json an already converted run
#   scripts/replay.sh --list [text]          replayable good runs, optionally filtered
#
# Verdicts go to logs/verdicts.jsonl. Needs `pi` on PATH (devenv shell).
set -euo pipefail
cd "$(dirname "$0")/.."

# traj_id, resolved, model, steps of the good runs the gate can replay.
replayable() {
  uv run python - "$@" <<'PY'
import csv, random, sys
rows = [r for r in csv.DictReader(open("subset/good_runs.csv")) if r["replayable"] == "True"]
if sys.argv[1] == "random":
    print(random.choice(rows)["traj_id"])
else:
    for r in rows:
        if sys.argv[2].lower() in r["traj_id"].lower():
            print(f'{r["traj_id"]}  {r["model"]}  patch_lines={r["patch_lines"]}')
PY
}

case "${1:-}" in
  -h|--help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
  --list) replayable list "${2:-}"; exit 0 ;;
  "") id=$(replayable random); echo "Replaying a random good run: $id" ;;
  *) id=$1 ;;
esac

if [[ -f $id ]]; then
  run=$id
else
  run="replays/$id.json"
  if [[ ! -f $run ]]; then
    HF_HUB_DISABLE_PROGRESS_BARS=1 uv run scripts/convert_runs.py --traj-id "$id"
    [[ -f $run ]] || { echo "Could not convert '$id' (not found, or not replayable). Try: scripts/replay.sh --list" >&2; exit 1; }
  fi
fi

command -v pi >/dev/null || { echo "pi not found on PATH. Run this inside 'devenv shell'." >&2; exit 1; }
COMMIT_FIRST_REPLAY="$run" exec pi \
  --extension ./extensions/commit-first/index.ts --no-extensions \
  --model replay/recorded-run \
  --no-builtin-tools --no-skills --no-context-files --no-mcp --no-session --offline
