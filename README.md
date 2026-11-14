# Commit-first review gate for pi

A [pi](https://github.com/earendil-works/pi) extension that pauses an agent run when the agent
submits its fix, and makes the human reviewer commit to a verdict on the raw evidence before
seeing the agent's own summary. Driven here by recorded SWE-smith runs.

## Run it live

Without `COMMIT_FIRST_REPLAY`, a real model does the work and the gate fires on its real `submit`
call. This path is untested.

1. Get a shell with pi and a model key. pi comes from this repo's devenv, so open the shell here
   and stay in it when you `cd` elsewhere:
   ```
   cd ~/repos/pivotal-winter-2027
   devenv shell
   export ANTHROPIC_API_KEY=...     # or OPENROUTER_API_KEY, OPENAI_API_KEY, …
   ```
2. Check out a task with the bug in place. Each SWE-smith instance is a branch of a mirror repo
   under `github.com/swesmith`:
   ```
   git clone -b pallets__markupsafe.620c06c9.pr_469 \
     https://github.com/swesmith/pallets__markupsafe.620c06c9 /tmp/live-run
   cd /tmp/live-run
   ```
   Any git repo with a committed `HEAD` also works; the gate takes the code change from
   `git diff HEAD`.
3. Start pi with the gate (add `--model <provider/id>` to pick a model; `pi --list-models` lists
   them):
   ```
   COMMIT_FIRST_LOG=~/repos/pivotal-winter-2027/logs/verdicts.jsonl \
     pi --extension ~/repos/pivotal-winter-2027/extensions/commit-first/index.ts
   ```
4. Give it the task: the instance's `problem_statement` from the SWE-smith dataset, wrapped so the
   gate shows only that text as the task. The last line matters, because the gate only fires if
   the agent calls `submit`:
   ```
   <pr_description>
   …problem statement…
   </pr_description>
   Fix this, run the tests, then call the submit tool.
   ```
5. Review when the run pauses on `submit`:
   - Step 1 shows the task, the diff and the output of test commands the agent ran. Press `a` or
     `d`.
   - Step 2 shows the agent's last messages above the same evidence. Press `a` or `d` for the
     final verdict.
   - Approve lets the submit through. Deny returns "Reviewer denied this submission." to the
     agent, which keeps working and can submit again, opening a new review.
6. Check the log. Each review writes two lines with the same `review_id`, `replay: false` and
   `traj_id: null`:
   ```
   cat ~/repos/pivotal-winter-2027/logs/verdicts.jsonl
   ```

Differences from the replay:

- Step 1 is not blind. The agent's messages stream into the pi transcript before the gate opens;
  the redaction is only in the replay provider.
- New files are missing from the diff. `git diff HEAD` skips untracked files.
- No ground truth. `resolved` is logged as `null`; nothing runs the hidden tests.

## Replay a recorded run

Inside the devenv shell (`devenv shell` or `direnv allow`), where `pi` and the `replay` command
come from:

```
replay                      # a random replayable run from the good-runs subset
replay --list [text]        # the 197 replayable good runs, optionally filtered
replay <traj_id>            # that run, converted on the fly
replay replays/<id>.json    # an already converted run
cat logs/verdicts.jsonl
```

`replay` is a devenv script for `scripts/replay.sh`. A run named by id is looked up in
`subset/good_runs.parquet` first (all shards, no dataset download), then in the first raw shard.
`uv run scripts/convert_runs.py` still converts a balanced sample of 4 from the first shard.

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
| `patch` column belongs to a different row (touches files the run never mentions) | 2320 of 2364 non-empty | Used only when `patch_match()` verifies it against the run; otherwise the code change is the diff `submit` printed for review, else rebuilt from the edit calls |
| `patch` empty | 649 (254 of them `resolved`) | same |
| Tool calls stored as `<function=...>` text, no structured `tool_calls` | 959 | Not convertible; skipped by the replay |
| Harness stopped the run without a submit ("Exit due to cost limit", …) | 138 | Exit line becomes a synthetic submit event, flagged `forced_exit`; excluded from sampling unless `--include-forced` |
| Two-step submit (first call only prints a checklist + diff) | 1380 | Gate fires on the last submit call |
| Several runs per instance | 161 extra | Keyed by `traj_id` |
| No SWE-smith row for the instance | 24 | Task taken from the `<pr_description>` in the agent prompt |
| Mixed content shapes, `\r\n`, `OBSERVATION:` prefix | all | Normalised |

`resolved` may be misaligned in the same way as `patch`: runs with no source edit through the
editor tool are marked resolved as often (49%) as runs with one (46%). Against that, an LLM
grader that never sees the label agrees with it on 76% of graded runs (`evals/`, 400-run sample),
where a shuffled label would give about 50%. Neither is a re-run of the tests; the label is logged
but should be re-derived before being used as ground truth.

## Good-runs subset

`uv run scripts/build_subset.py` scans all 8 cached shards of the `tool` split (24,100 runs),
joins each run to its SWE-smith task row, and keeps the runs whose patch provably belongs to them:

| Step | Runs |
|---|---|
| all runs | 24,100 |
| `patch` non-empty | 18,156 |
| patch matches the trajectory (every file mentioned, ≥ 90% of added lines found in the run's tool calls or output) | 364 |
| instance has a SWE-smith task row | **350** |

Output, both committed: `subset/good_runs.parquet` (full merged rows, about 6 MB) and
`subset/good_runs.csv` (manifest). Of the 350, 197 are replayable in the gate as is (structured
tool calls and a real submit); 151 use the text tool-call format. 145 are repeat runs of an
instance already in the subset, and for 62 the SWE-smith problem statement differs from the one in
the agent's prompt (`task_matches_prompt`). The subset is not a random sample: the match rule
favours runs whose changes are visible in the transcript.

### Using the subset

The parquet is a data file; open it with one of these:

- **Browse it:** `run` (see [Trajectory viewer](#trajectory-viewer)). It is the viewer's default
  data.
- **Query it** with duckdb, for example runs by model and label:
  ```
  uv run python -c "
  import duckdb
  print(duckdb.sql(\"select model, resolved, count(*) from 'subset/good_runs.parquet' group by all order by all\"))
  "
  ```
- **Rebuild it** from the datasets: `uv run scripts/build_subset.py` (a few minutes).

Columns: the trajectory's own (`messages`, `instance_id`, `resolved`, `model`, `traj_id`, `patch`),
the task's from SWE-smith (`repo`, `problem_statement`, `bug_patch`, `FAIL_TO_PASS`,
`PASS_TO_PASS`, `image_name`), and the check columns that are also in the CSV.

To review one of these runs in the gate, use `replay <traj_id>` (see
[Replay a recorded run](#replay-a-recorded-run)); 197 of the 350 are replayable.

## Trajectory viewer

```
devenv shell        # or: direnv allow
run                 # http://127.0.0.1:8765/
```

`run` is a devenv script for `uv run scripts/serve_viewer.py`; arguments pass through
(`run --port 9000`, `run --raw`).

Opens on the 350 good runs in `subset/good_runs.parquet`, which ships with the repo, so it works
on a fresh clone without downloading the datasets.

- **Trajectories to review to the left**, with search and filters for resolved, ending and model.
- **Top:** run header with the task, the code change and the agent's prompt.
- **Middle:** the steps left to right, one chip per agent turn, shaped and coloured by tool (bash,
  view, create, edit, submit). The gated submit has a star; outputs that look like errors have a
  red "!" (a text heuristic, it can over-flag).
- **Below:** the selected step's narration, tool call and output. Arrow keys move between steps.

Other data: `--raw` browses the first raw shard (3013 runs, needs the Hugging Face cache) and
`--data <file.parquet>` any parquet with the trajectory columns.

## Known limits

- The review-output diff is from before the agent's cleanup, so it can include its scratch scripts
  (existing-file edits are sorted first). Rebuilt diffs are an edit log, not a true diff.
- "Test output" is whatever the agent chose to run, often its own repro script. The hidden
  FAIL_TO_PASS tests are never run in a trajectory.
- The "summary" is the agent's last messages (up to 3, back to about 400 characters), a heuristic.
