# Decisions and why

What was decided while building the commit-first review gate, in the order the questions came up.
Counts are from the `tool` split of `SWE-bench/SWE-smith-trajectories`: 3,013 runs in the first
shard, 24,100 across all 8.

## The mechanism

| Decision | Why |
|---|---|
| Build the gate as a pi extension that hooks the `tool_call` event for `submit` | It is pi's own blocking hook: the run pauses there, and a deny can stop the submit. |
| Replay through pi's real agent loop: a `replay` model provider emits the recorded assistant turns, and stand-in `bash` / `str_replace_editor` / `submit` tools return the recorded output | The gate then receives the same events it would from a live agent, so the replay tests the actual hook, not a simulation of it. Nothing recorded is executed. |
| Two review steps: evidence only (task, code change, test output), then the agent's summary above the same evidence | This is the "commit first" idea: the reviewer forms a verdict before the agent's pitch can anchor it. |
| Write the blind verdict to the log before step 2 renders; two log lines per review sharing a `review_id` | The first verdict cannot be revised after the reveal, and it survives if the reviewer quits midway. |
| Redact agent narration in the transcript too, and show the review as a full-screen overlay | Otherwise the reviewer could read the summary by scrolling up, and the blind step would not be blind. |
| Gate on the last `submit` call of a run | Submit is two-step in 1,380 first-shard runs: the first call only prints a checklist and the diff. The last call is the real submission. |
| A final deny ends a replay; a live agent would get the denial as the tool result and continue | A recording cannot react to a denial. |
| Log the dataset's `resolved` label but never show it | It is the outcome to compare verdicts against; showing it would defeat the review. |
| Show the agent's last messages (up to three, back to about 400 characters) as its "summary" | The very last message is often housekeeping ("removing scripts, submitting again"), not the pitch. |
| With no reviewer UI, block the submit | Fail closed: no verdict means no approval. |

## The data

| Decision | Why |
|---|---|
| Do not trust the `patch` column by default | In the first shard, 2,320 of 2,364 non-empty patches touch files the run never mentions (an apispec run carries a flashtext patch). The column belongs to other rows. I tested for a fixed row offset and found none. |
| Verify a patch against its own trajectory (`patch_match`): every file mentioned, and at least 90% of added lines found in the run's tool calls or output | "Files mentioned" alone is too weak: 44 first-shard patches pass it, but only 9 pass the added-lines check. |
| Code change shown, in order: verified dataset patch, else the diff `submit` printed for review, else a pseudo-diff rebuilt from the edit calls | The verified patch is the final, post-cleanup one. The other two come from the trajectory itself, so they at least belong to the run. |
| Build a "good runs" subset instead of repairing the majority | About 98% of non-empty patches fail verification, and time was short. Empty patches are dropped too. |
| Scan all 8 shards for the subset | The first shard yields only 9 good runs; all shards yield 350 after joining to SWE-smith task rows. |
| Join to `SWE-bench/SWE-smith` on `instance_id` and keep the task columns in the subset file | The reviewer needs the task, and the subset then works without the dataset download. |
| Treat `resolved` as unverified | Runs with no source edit through the editor tool are marked resolved as often (49%) as runs with one (46%). The check is crude (it misses edits made through `bash`), so this is a suspicion, not a finding. |
| Turn a harness exit ("Exit due to cost limit") into a synthetic submit flagged `forced_exit`, and leave those runs out of sampling by default | There is no submit event to hook, and no agent summary to reveal. |
| Skip runs that store tool calls as `<function=...>` text | The converter reads structured `tool_calls` only. This is 959 first-shard runs. |

A correction made along the way: I first reported 1,109 first-shard runs as harness exits. Only 138
are; 959 are the text tool-call format. The README was fixed.

## What must be fixed before measuring effectiveness

Decided as the priority order, given limited time:

1. **Re-derive the ground truth.** Without a trustworthy `resolved`, there is no outcome to score
   verdicts against. Apply each run's own diff in its SWE-smith image and run the `FAIL_TO_PASS`
   tests, on the study runs only.
2. **Use only runs with a trustworthy code change.** That is the 350-run subset.
3. **Exclude runs with no real summary.** The intervention is the contrast between evidence and
   pitch; harness-stopped runs have no pitch.

Handled by sampling, not fixing: one run per instance (145 of the 350 are repeats), stratify by
resolved, state the model mix. Stated as a limit: "test output" is whatever the agent chose to
run; the hidden tests never run inside a trajectory.

## Tooling around the gate

| Decision | Why |
|---|---|
| Trajectory viewer as one static page plus a stdlib server, no build step | Simple to run and to ship; it reuses `convert_runs.convert()` so the viewer and the gate read runs the same way. |
| Viewer opens on the 350 good runs by default; `--raw` and `--data` select other data | These are the runs worth reviewing, and the default works on a fresh clone. |
| Ship `subset/good_runs.parquet` (about 6 MB) in the repo | So the default view needs no Hugging Face download. It moved out of the git-ignored `data/`. |
| `run` as a devenv script | One command after `devenv shell` or `direnv allow` starts a review. |
| Inspect eval with an LLM grader over 400 seeded trajectories; scores: transcript summary and agent errors, data problems, summary faithfulness, grader-predicted resolved vs the label | Faithfulness measures the risk the gate targets (the agent overclaiming). Predicted-vs-label is a cheap check on whether `resolved` is aligned. Data-problem flags are computed in code, not by the grader. |
| Do not run the full 400 against a real model without asking | It spends API budget. It was smoke-tested with a mock model and 3 real samples. |
| Fan the viewer and the eval out to two subagents | Independent work, done in parallel. |

## Repository

| Decision | Why |
|---|---|
| Move the OpenRouter key and Hugging Face token from `.envrc` to a git-ignored `.envrc.local` | "Commit everything" would have put literal keys in a repo with a GitHub remote. `.envrc` now loads the local file, so the environment behaves the same. |
| Scan commits for key patterns before committing and before pushing | Same reason; both scans found none. |
| Make the vendored `docs/` and `examples/` user-writable | They were read-only copies, which blocked git from switching branches and merging. |
| Everything merged to `main` and pushed to `origin` | As requested. |

## Still open

- `resolved` has not been verified.
- The Inspect eval samples from the first shard, not from the good-runs subset, and the full 400
  has not been run.
- The live-agent path of the gate (a real `submit`, code change from `git diff HEAD`) is untested.
- 151 of the 350 good runs use the text tool-call format, so 197 are replayable in the gate as is.
- The subset is not a random sample: the match rule favours runs whose changes are visible in the
  transcript.
- Part B is not written.
