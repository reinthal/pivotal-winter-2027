# Trajectory audit (Inspect eval)

Scores recorded SWE-smith agent runs with an LLM grader. The runs already happened, so the solver
does nothing; the scorer sends a rendered transcript to the grader and combines its JSON reply with
data checks computed in code. Design notes are in the docstring of `trajectory_audit.py`.

## Run

```
uv run scripts/download_trajectories.py      # once: datasets -> HF cache
uv run evals/smoke_test.py                   # offline, mock grader, 8 samples, no API calls

# 3 real samples (needs a provider key in the environment, e.g. OPENROUTER_API_KEY)
uv run inspect eval evals/trajectory_audit.py -T limit=3 -T include_rejected=false \
    --model-role grader=openrouter/anthropic/claude-haiku-5.5

# the full 400
uv run inspect eval evals/trajectory_audit.py \
    --model-role grader=openrouter/anthropic/claude-haiku-5.5 --max-connections 20

uv run inspect view                          # browse ./logs
```

The grader is the `grader` model role, so any Inspect model works (`--model-role grader=...`).
OpenRouter models need the `openai` package, which is already a dependency; other providers need
their own SDK (`uv add anthropic`, ...).

Task arguments (`-T name=value`):

| Argument | Default | Meaning |
|---|---|---|
| `limit` | 400 | trajectories to sample |
| `seed` | 0 | sampling seed |
| `shard` | 0 | which `tool-*.parquet` shard |
| `max_chars` | 60000 | approximate transcript size sent to the grader |
| `include_rejected` | true | keep rows `convert()` rejects as ungraded samples; `false` samples only gradable rows |

## Cost

With the defaults about 280 of the 400 samples reach the grader (the rest are rows `convert()`
rejects, recorded without a grader call). Measured on 3 real samples: about 15k input and 1.1k
output tokens each. So the full run is roughly 4-5M input and 0.3-0.4M output tokens: under $1 at
$0.10 / $0.50 per million tokens, about $6-7 at $1 / $5. With `include_rejected=false` all 400 are
graded, about 40% more.

## What is scored

One dict-valued score per sample; each key gets its own mean (and stderr for the main ones) in the
log viewer. The free text is in the score explanation, the full grader JSON in the score metadata.

| Keys | Source | Meaning |
|---|---|---|
| `error_count`, `major_error_count`, `err_<category>` | grader | Agent errors. Each `err_*` is 0/1, so its mean is the share of runs with that error. The summary text is in the explanation |
| `data_problem_count`, `dp_*` | code, except `dp_grader_observed` | Data problems of the row. `dp_grader_observed` counts what the grader noticed in the transcript |
| `summary_faithfulness` (0-1), `overclaim` (0/1) | grader | Whether the agent's closing summary is supported by the diff and tool output. `overclaim` = 1 when at least one material claim is unverified or contradicted |
| `predicted_resolved`, `label_agreement`, `label_resolved` | grader vs dataset | The grader's blind guess whether the fix works, and whether it matches the dataset's `resolved` label |
| `grader_ok` | code | 1 valid reply, 0 unusable after one retry |

NaN means "does not apply" (row not graded, grader failed, or no agent summary because the harness
stopped the run). Inspect leaves NaN out of that key's mean and counts it as unscored.

## Caveats

- The dataset's `resolved` label is not verified and the grader is not ground truth either.
  `label_agreement` is a consistency check between the two, nothing more.
- The grader sees a shortened transcript: long observations keep head and tail, and long runs lose
  steps from the middle. Cuts are marked in the text and counted in the sample metadata (`render`).
- About 30% of sampled rows are rejected by `convert()`, nearly all because their tool calls are
  `<function=...>` text inside assistant messages instead of structured `tool_calls`
  (`dp_xml_tool_calls`).
