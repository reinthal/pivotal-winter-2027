# Walkthrough manuscript (3 minutes)

About 420 spoken words. Each step lists what is on screen and what to say.

## Before recording

- Terminal 1, in `devenv shell`, with this typed but not run:
  `scripts/replay.sh replays/pydantic__pydantic.acb0f10f.pr_8316.h88r46b0.json`
- Terminal 2: `uv run scripts/convert_runs.py --stats` already run, output visible.
- Browser tab 1: the viewer (`run`, then http://127.0.0.1:8765/).
- Browser tab 2: `uv run inspect view`, open on the MONAI sample
  `Project-MONAI__MONAI.a09c1f08.pr_2238.h88r46b0`.
- Editor: `README.md` at the "Data problems" table.

## 1. What I built (0:00 – 0:20)

**Screen:** README, top.

> I built a commit-first review gate as an extension for the pi coding agent. When the agent
> submits its fix, the run pauses. The reviewer first judges the raw evidence, commits to a
> verdict, and only then sees the agent's own summary. Both verdicts are logged.

## 2. The data was the hard part (0:20 – 1:00)

**Screen:** Terminal 2 with the `--stats` output, then the README data-problems table.

> The recorded runs needed work before I could replay them. The biggest problem: the patch
> column does not belong to its row. In the first shard, 2,320 of 2,364 non-empty patches touch
> files the run never mentions. An apispec run carries a flashtext patch.
>
> So I verify each patch against its own trajectory, and keep only the runs that pass: 350 out of
> 24,100, merged with their SWE-smith task. That subset ships with the repo.
>
> Other problems: about a third of runs store tool calls as text and can't be replayed, some runs
> are stopped by the harness and never submit, and submit is two-step, so I gate on the last call.

## 3. Replay one run (1:00 – 2:00)

**Screen:** Terminal 1. Press Enter to start the replay.

> The extension replays a recorded run through pi's real agent loop, so the gate gets the same
> events a live agent would produce. Nothing is executed.

**Screen:** step 1 of the review. Scroll down once through the diff and test output.

> Here the run has paused at submit. Step one shows only the task, the code change and the test
> output. The agent's narration is hidden, in the transcript too. I'll deny.

**Action:** press `d`.

> Now step two: the agent's summary appears above the same evidence. It is confident and well
> written. I can keep or change my verdict. I'll keep deny.

**Action:** press `d`. Then show `tail -2 logs/verdicts.jsonl`.

> Two log lines: the blind verdict, written before the reveal so it can't be revised, and the
> final one, with whether it changed and the time each took.

## 4. Why this design, and what the reviewer sees (2:00 – 2:30)

**Screen:** Browser tab 2, the MONAI sample in Inspect.

> Why hide the summary? I tagged 400 runs with an LLM grader. In about two thirds of graded runs,
> the agent's summary claims more than the evidence supports. In this one it says all edge cases
> are handled, but it never ran the project's tests. The gate makes the reviewer look at the
> evidence before the pitch.

**Screen:** Browser tab 1, the viewer, click through two steps.

> For reading whole runs there is also a step-by-step viewer.

## 5. What did not work, and next (2:30 – 3:00)

**Screen:** README, "Known limits".

> What I'd flag. The resolved label is not verified: the grader agrees with it 76% of the time,
> which suggests it is aligned, but I would re-run the hidden tests before using it as ground
> truth. Only 197 of the 350 good runs replay in the gate today. The live-agent path is untested.
> And the test output shown is whatever the agent chose to run.
>
> Next: verify the labels on a small sample, then run the study from Part B on the good subset.

## If you run short on time

Cut the viewer in step 4 first, then the "other problems" paragraph in step 2. Keep the replay.
