# Commit-first review gate for pi

A [pi](https://github.com/earendil-works/pi) extension that pauses an agent run when the agent
submits its fix, and makes the human reviewer commit to a verdict on the raw evidence before
seeing the agent's own summary. Driven here by recorded SWE-smith runs.

```
uv run scripts/download_trajectories.py        # datasets -> HF cache
uv run scripts/convert_runs.py                 # 4 recorded runs -> replays/*.json (2 resolved, 2 not)
scripts/replay.sh replays/<traj_id>.json       # replay one in pi (pi comes from devenv)
cat logs/verdicts.jsonl
```

Keys in the review screen: `a` approve, `d` deny, arrows / PgUp / PgDn / Space to scroll, Esc aborts
(the submit is then blocked).

## Verify Part A

Run inside the devenv shell (that is where `pi` comes from).

1. Prepare the data (skip if cached; `replays/` already holds converted runs):
   ```
   uv run scripts/download_trajectories.py
   uv run scripts/convert_runs.py
   ```
2. Replay one run:
   ```
   scripts/replay.sh replays/pallets__markupsafe.620c06c9.pr_469.1cm1w3ln.json
   ```
3. Check each requirement from `task.md` as you go:

   | Requirement | What you should see |
   |---|---|
   | Pauses on submit | The recorded turns play, then a full-screen review opens when the agent calls `submit`. |
   | Raw evidence only | The screen shows the task, the code change and the test output. Agent narration reads `[agent narration withheld …]`, in the transcript too. |
   | First verdict | Press `a` (approve) or `d` (deny). |
   | Summary revealed, verdict can change | The agent's closing messages appear above the same evidence. Press the other key to flip the verdict. |
   | Both verdicts logged | See step 4. |

4. Check the log:
   ```
   cat logs/verdicts.jsonl
   ```
   Expect two lines with the same `review_id`: one with `phase: "blind"` and one with
   `phase: "informed"`. The informed line carries `blind_verdict`, and `changed: true` if you
   flipped.
5. Cover the other paths by replaying a second run:
   - Give a final deny and confirm the submit is blocked and the replay ends.
   - Press Esc in the review and confirm the submit is blocked.

These steps do not cover the live-agent path (without `COMMIT_FIRST_REPLAY`).

## What happens

1. `scripts/convert_runs.py` turns a dataset row into a replay file: the assistant turns, the tool
   output keyed by tool-call id, the task, the code change, and which submit call is the real one.
2. `extensions/commit-first/index.ts`, with `COMMIT_FIRST_REPLAY` set, registers a `replay` model
   provider that emits the recorded assistant turns and `bash` / `str_replace_editor` / `submit`
   tools that return the recorded output. pi's own agent loop then fires its normal `tool_call` /
   `tool_result` events for a run that already happened. Nothing recorded is executed.
3. The gate is a `tool_call` handler on `submit`:
   - **Step 1, blind.** Full-screen view of task, code change, and the output of the test/script
     commands the agent ran. Agent narration is withheld, in the transcript too (replaced by
     `[agent narration withheld …]`). The verdict is appended to the log before step 2 renders.
   - **Step 2, informed.** The agent's closing messages appear above the same evidence. The
     reviewer gives a final verdict.
   - Final deny blocks the submit (and ends a replay; a live agent would get the denial as the
     tool result and continue).
4. `logs/verdicts.jsonl` gets two lines per review sharing a `review_id`: `phase: "blind"` and
   `phase: "informed"` (with `blind_verdict`, `changed`, seconds per phase, and the dataset's
   `resolved` label, which the reviewer never sees).

The gate reads only pi events, so without `COMMIT_FIRST_REPLAY` it gates a live agent's `submit`
tool and takes the code change from `git diff HEAD`. That path is untested.

## Data problems (`uv run scripts/convert_runs.py --stats`, first `tool` shard, 3013 runs)

| Problem | Count | Handling |
|---|---|---|
| `patch` column belongs to a different row (touches files the run never mentions) | 2320 of 2364 non-empty | Not used. Code change comes from the trajectory: the diff `submit` printed for review, else rebuilt from the edit calls |
| `patch` empty | 649 (254 of them `resolved`) | same |
| No `submit` call; harness stopped the run ("Exit due to cost limit", context overflow, …) | 1109 | Exit line becomes a synthetic submit event, flagged `forced_exit`; excluded from sampling unless `--include-forced` |
| Two-step submit (first call only prints a checklist + diff) | 1380 | Gate fires on the last submit call |
| Several runs per instance | 161 extra | Keyed by `traj_id` |
| No SWE-smith row for the instance | 24 | Task taken from the `<pr_description>` in the agent prompt |
| Mixed content shapes, `\r\n`, `OBSERVATION:` prefix | all | Normalised |

`resolved` may be misaligned in the same way as `patch`: runs with no source edit through the
editor tool are marked resolved as often (49%) as runs with one (46%). Not verified further; it is
logged but should be re-derived before being used as ground truth.

## Known limits

- The review-output diff is from before the agent's cleanup, so it can include its scratch scripts
  (existing-file edits are sorted first). Rebuilt diffs are an edit log, not a true diff.
- "Test output" is whatever the agent chose to run, often its own repro script. The hidden
  FAIL_TO_PASS tests are never run in a trajectory.
- The "summary" is the agent's last messages (up to 3, back to about 400 characters), a heuristic.
