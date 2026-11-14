"""Offline check of evals/trajectory_audit.py with Inspect's mock model.

    uv run evals/smoke_test.py

No API calls. Runs 8 samples with scripted grader replies that cover: valid
JSON, valid JSON inside a markdown fence, garbage then valid JSON (retry
succeeds), garbage twice (sample recorded as unscored), and rows convert()
rejects (no grader call). Also checks the default dataset has 400 samples.
"""

import json
import math
import sys
import tempfile
from pathlib import Path

from inspect_ai import eval
from inspect_ai.model import ModelOutput, get_model

sys.path.insert(0, str(Path(__file__).resolve().parent))
from trajectory_audit import trajectory_audit  # noqa: E402

GOOD = json.dumps({
    "transcript_summary": "The agent fixed the bug but only ran its own script.",
    "errors": [
        {"category": "weak_verification", "severity": "major", "step": 7, "description": "Never ran the test suite."},
        {"category": "not-a-category", "severity": "minor", "step": None, "description": "Mapped to other."},
    ],
    "data_problems_observed": [{"category": "garbled_observation", "description": "Step 3 output is binary."}],
    "summary_faithfulness": 3,
    "unsupported_claims": ["all tests pass"],
    "p_resolved": 0.7,
    "resolved_rationale": "The change matches the task.",
})
BAD = "Sure! Here is my analysis: the agent did fine."
BAD_SCHEMA = json.dumps({"transcript_summary": "x", "errors": [], "p_resolved": 7})  # out of range, field missing
REPLIES = [GOOD, f"```json\n{GOOD}\n```", BAD, GOOD, BAD_SCHEMA, BAD] + [GOOD] * 20


def main() -> None:
    assert len(trajectory_audit().dataset) == 400, "default task should have 400 samples"
    print("default dataset: 400 samples")

    grader = get_model("mockllm/model", custom_outputs=[ModelOutput.from_content("mockllm/model", r) for r in REPLIES])
    with tempfile.TemporaryDirectory() as log_dir:
        log = eval(trajectory_audit(limit=8), model="mockllm/model", model_roles={"grader": grader},
                   max_samples=1, log_dir=log_dir, display="none")[0]
        assert log.status == "success", log.error
        assert log.samples and len(log.samples) == 8

        ok = []
        for s in log.samples:
            score = s.scores["trajectory_audit_scorer"]
            v = score.value
            print(f"{str(s.id)[:44]:44} grader_ok={v['grader_ok']} errors={v['error_count']} "
                  f"data_problems={v['data_problem_count']} | {score.explanation.splitlines()[0][:60]}")
            if s.metadata["rejected_reason"]:
                assert math.isnan(v["grader_ok"]) and v["dp_rejected"] == 1
                assert not s.output.completion, "solver must not generate"
            else:
                ok.append(v["grader_ok"])
                if v["grader_ok"] == 1:
                    assert v["error_count"] == 2 and v["err_other"] == 1 and v["err_weak_verification"] == 1
                    assert v["dp_grader_observed"] == 1
                    assert v["label_agreement"] == int(s.metadata["label_resolved"])  # mock predicts resolved
                    if not s.metadata["forced_exit"]:
                        assert v["summary_faithfulness"] == 0.5 and v["overclaim"] == 1
                else:
                    assert "UNSCORED" in score.explanation and math.isnan(v["error_count"])
        # Samples run one at a time but the log lists them by id, so check counts:
        # one retry that succeeds and one double failure leave exactly one 0.
        assert ok.count(0) == 1 and ok.count(1) == len(ok) - 1, ok
        assert len(ok) < 8, "expected at least one rejected row among the first 8 samples"

        print("\nmetrics:")
        for s in log.results.scores:
            m = ", ".join(f"{k}={v.value:.3f}" for k, v in s.metrics.items())
            print(f"  {s.name:26} {m}  (scored {s.scored_samples}, unscored {s.unscored_samples})")
    print("\nsmoke test passed")


if __name__ == "__main__":
    main()
