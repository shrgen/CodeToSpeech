"""promptfoo custom provider: runs one golden case through the real ClaimSense pipeline.

Used by evals/promptfoo-golden.yaml (the agreement runner). Output is the graded case as
JSON, so promptfoo asserts on the same pass/fail the execution-graded gate computes.
Brain: env CLAIMSENSE_BRAIN (default mock).
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from claimsense.brain import get_brain  # noqa: E402
from claimsense.evalsuite import load_suite, official_clause_ids, run_case  # noqa: E402
from claimsense.release import active  # noqa: E402
from claimsense.trace import Tracer  # noqa: E402

_CASES = {c["case_id"]: c for c in load_suite("golden")["cases"]}
_STATE = {}


def call_api(prompt, options, context):
    if not _STATE:
        _STATE.update(brain=get_brain(os.environ.get("CLAIMSENSE_BRAIN", "mock")), release=active(),
                      tracer=Tracer(), official=official_clause_ids(), cache={})
    case = _CASES[context["vars"]["case_id"]]
    r = run_case(case, _STATE["brain"], _STATE["release"], _STATE["tracer"], _STATE["official"], _STATE["cache"])
    return {"output": json.dumps({"case_id": r.case_id, "passed": r.passed, "outcome": r.outcome,
                                  "expected": r.expected, "verdict_source": r.verdict_source,
                                  "failures": r.failures})}
