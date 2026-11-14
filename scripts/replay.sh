#!/usr/bin/env bash
# Replay one recorded run in pi with the commit-first gate.
#   scripts/replay.sh replays/<traj_id>.json
set -euo pipefail
cd "$(dirname "$0")/.."
run="${1:?usage: scripts/replay.sh replays/<traj_id>.json}"
COMMIT_FIRST_REPLAY="$run" exec pi \
  --extension ./extensions/commit-first/index.ts --no-extensions \
  --model replay/recorded-run \
  --no-builtin-tools --no-skills --no-context-files --no-mcp --no-session --offline
