"""Ablation: does the gate actually depend on the guards? Runs the golden suite three ways.

  full        quarantine on, output guardrail on        (the shipped configuration)
  no_quarant  input quarantine off, guardrail on
  unguarded   quarantine off AND guardrail accepts everything

Writes runs/ablation.json. If 'unguarded' still passed every adversarial case, those cases
would be testing nothing; this run shows which ones depend on which guard.
    python3 ops/ablation.py
"""
from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import claimsense.pipeline as pipeline_mod  # noqa: E402
from claimsense.brain import MockBrain  # noqa: E402
from claimsense.evalsuite import load_suite, run_suite  # noqa: E402
from claimsense.guardrail import GuardResult, check  # noqa: E402
from claimsense.release import Release  # noqa: E402


def main() -> None:
    suite, base = load_suite("golden"), Release.load("v1.0.0")
    out = {}
    for name, quarantine, guard in [("full", True, True), ("no_quarantine", False, True), ("unguarded", False, False)]:
        pipeline_mod.check = check if guard else (lambda *a, **k: GuardResult(True, []))
        rep = run_suite(suite, MockBrain(), replace(base, quarantine=quarantine))
        adv = [r for r in rep["results"] if r["family"] == "adversarial"]
        out[name] = {"quarantine": quarantine, "output_guardrail": guard, "passed": rep["passed"],
                     "cases": rep["cases"], "pass_rate": rep["pass_rate"], "gate_passed": rep["gate_passed"],
                     "adversarial_passed": sum(r["passed"] for r in adv), "adversarial_total": len(adv),
                     "adversarial_failures": rep["adversarial_failures"],
                     "adversarial_passing_anyway": [r["case_id"] for r in adv if r["passed"]]}
        print(f"{name:<14} {rep['passed']}/{rep['cases']}  adversarial {out[name]['adversarial_passed']}/"
              f"{len(adv)}  gate {'PASSED' if rep['gate_passed'] else 'FAILED'}")
    pipeline_mod.check = check
    (ROOT / "runs" / "ablation.json").write_text(json.dumps(out, indent=1) + "\n")


if __name__ == "__main__":
    main()
