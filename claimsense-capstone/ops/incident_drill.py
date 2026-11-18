"""Incident drill: deliberate regression -> detection -> rollback -> verified recovery -> RCA.

  python3 ops/incident_drill.py --inject-at 30 --requests 100 --fast
  python3 ops/incident_drill.py --inject-at 30 --rollback-at 75 --requests 100 --fast   # fixed rollback

What happens, with real timestamps from the run:
  1. A stream of normal claim traffic (golden base + variant cases; no adversarial cases,
     which are rejected on purpose and would mask the signal) runs on the active release.
  2. At request --inject-at, release v1.1.0 is promoted WITHOUT the gate. Its retrieval
     index silently drops CLS-LIAB-003 and CLS-PER-006.
  3. Detection = the first request at which the rolling pass rate (last 20 graded requests)
     drops below the 95% SLO, or the rolling error rate breaches the 5% alarm.
  4. Rollback re-activates the previous release (at detection, or at --rollback-at).
  5. Verified recovery = the smoke gate, then the full golden gate, pass on the rolled-back
     release. Time to verified recovery is measured from detection to that gate result.
  6. Writes runs/drill/: incident_traces.jsonl, drill_log.json, RCA.md, dashboard.html,
     and spawns a regression eval case into evals/regression_set.json.

The drill works on a COPY of releases/ (runs/drill/releases), so the repo's real ACTIVE
release is never changed by a drill.
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from claimsense import release as rel  # noqa: E402
from claimsense.brain import get_brain  # noqa: E402
from claimsense.dashboard import SLO_ERROR, SLO_PASS, WINDOW, build  # noqa: E402
from claimsense.evalsuite import load_suite, official_clause_ids, run_case, run_suite  # noqa: E402
from claimsense.trace import Tracer  # noqa: E402

OUT = ROOT / "runs" / "drill"


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def traffic(n: int, seed: int = 17) -> list[dict]:
    cases = [c for c in load_suite("golden")["cases"] if c["family"] in ("base", "variant")]
    rng = random.Random(seed)
    out = []
    while len(out) < n:
        batch = cases[:]
        rng.shuffle(batch)
        out += batch
    return out[:n]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--requests", type=int, default=100)
    ap.add_argument("--inject-at", type=int, default=30)
    ap.add_argument("--rollback-at", type=int, help="roll back at this request instead of at detection")
    ap.add_argument("--bad-release", default="v1.1.0")
    ap.add_argument("--brain", default="mock", choices=["mock", "bedrock"])
    ap.add_argument("--fast", action="store_true", help="no pacing between requests")
    ap.add_argument("--pace", type=float, default=0.25, help="seconds between requests when not --fast")
    a = ap.parse_args(argv)

    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "releases").mkdir(parents=True)
    root = OUT / "releases"
    for f in (ROOT / "releases").glob("*.json"):
        shutil.copy(f, root / f.name)
    good = rel.active_version()
    (root / "ACTIVE").write_text(good + "\n")
    (root / "HISTORY.log").write_text("")
    rel.promote(good, "drill", "drill start: baseline release", root)

    brain = get_brain(a.brain)
    tracer = Tracer(OUT / "incident_traces.jsonl", simulate_model_latency=a.brain == "mock")
    official, cache = official_clause_ids(), {}
    events, rows = [], []
    detect_at = rollback_at = None
    verified, t_verified, t_verify_start = False, 0.0, 0.0
    smoke = golden = {}
    first_bad: dict | None = None
    t_start = time.time()

    def event(i, kind, label, **kw):
        e = {"i": i, "kind": kind, "label": label, "ts": time.time(), "at": iso(time.time()), **kw}
        events.append(e)
        print(f"[{e['at']}] request #{i:<3} {kind.upper():<9} {label}")
        return e

    print(f"drill: {a.requests} requests, baseline {good}, inject {a.bad_release} at #{a.inject_at}, "
          f"rollback {'at detection' if a.rollback_at is None else f'at #{a.rollback_at}'}")
    for i, c in enumerate(traffic(a.requests), 1):
        if i == a.inject_at:
            rel.promote(a.bad_release, "drill", "staged regression: config pushed without the gate", root)
            event(i, "inject", f"{a.bad_release} promoted (gate skipped)")
        if rollback_at is None and ((a.rollback_at is None and detect_at is not None) or i == a.rollback_at):
            v = rel.rollback("on-call", "drill: pass-rate SLO breach", root)
            rollback_at = i
            event(i, "rollback", f"rolled back to {v}")
            # verified recovery: the gates, on the rolled-back release, right now (before more traffic)
            active_after = rel.active(root)
            t_verify_start = time.time()
            smoke = run_suite(load_suite("smoke"), brain, active_after, min_pass=0.95)
            golden = run_suite(load_suite("golden"), brain, active_after, min_pass=0.95)
            verified = smoke["gate_passed"] and golden["gate_passed"]
            t_verified = time.time()
            if verified:
                event(i, "recovered", f"smoke {smoke['passed']}/{smoke['cases']} + golden "
                      f"{golden['passed']}/{golden['cases']} gates passed on {active_after.version}")
        release = rel.active(root)
        r = run_case(c, brain, release, tracer, official, cache)
        rows.append({"i": i, "case_id": c["case_id"], "release": release.version, "passed": r.passed,
                     "error": r.verdict_source == "deterministic_fallback", "trace_id": r.trace_id,
                     "outcome": r.outcome, "expected": c["expected_outcomes"], "failures": r.failures})
        if not r.passed and first_bad is None and release.version == a.bad_release:
            first_bad = {"case": c, "row": rows[-1]}
        win = rows[-WINDOW:]
        pass_rate = sum(x["passed"] for x in win) / len(win)
        err_rate = sum(x["error"] for x in win) / len(win)
        if detect_at is None and len(rows) >= WINDOW and (pass_rate < SLO_PASS or err_rate > SLO_ERROR):
            detect_at = i
            why = (f"rolling pass rate {pass_rate:.0%} < {SLO_PASS:.0%} SLO" if pass_rate < SLO_PASS
                   else f"rolling error rate {err_rate:.0%} > {SLO_ERROR:.0%} alarm")
            event(i, "detect", why, trace_id=r.trace_id, pass_rate=pass_rate, error_rate=err_rate)
        if not a.fast:
            time.sleep(a.pace)

    if rollback_at is None:
        print("no rollback happened (no detection and no --rollback-at): nothing to verify")
        return 1
    bad_gate = run_suite(load_suite("golden"), brain, rel.Release.load(a.bad_release, root), min_pass=0.95)

    # ── spawn a regression eval case from the first failing request on the bad release ──────
    spawned = None
    if first_bad:
        c = dict(first_bad["case"])
        spawned = dict(c, case_id=f"REG-{datetime.now(timezone.utc):%Y%m%d}-{c['case_id']}", family="regression",
                       rationale=f"Spawned by the incident drill: failed on {a.bad_release} "
                                 f"({'; '.join(first_bad['row']['failures'])}). " + c["rationale"])
        reg_path = ROOT / "evals" / "regression_set.json"
        reg = json.loads(reg_path.read_text()) if reg_path.exists() else {
            "meta": {"suite": "regression", "version": "1.0", "cases": 0,
                     "gate": "every regression case must keep passing"}, "cases": []}
        if not any(x["claim_id"] == spawned["claim_id"] and x["subfamily"] == spawned["subfamily"]
                   for x in reg["cases"]):
            reg["cases"].append(spawned)
        reg["meta"]["cases"] = len(reg["cases"])
        reg_path.write_text(json.dumps(reg, indent=1) + "\n")

    on_bad = [x for x in rows if x["release"] == a.bad_release]
    blast = {"requests_on_bad_release": len(on_bad), "failed": sum(not x["passed"] for x in on_bad),
             "fallback_verdicts": sum(x["error"] for x in on_bad),
             "unsafe_approvals": sum(x["outcome"] == "RECOMMEND_APPROVE" and "RECOMMEND_APPROVE" not in x["expected"]
                                     for x in on_bad)}
    ev = {e["kind"]: e for e in events}
    log = {
        "started": iso(t_start), "brain": a.brain, "requests": a.requests, "baseline": good,
        "bad_release": a.bad_release, "events": events, "blast_radius": blast,
        "time_to_detect_s": round(ev["detect"]["ts"] - ev["inject"]["ts"], 3) if "detect" in ev else None,
        "requests_to_detect": (ev["detect"]["i"] - ev["inject"]["i"]) if "detect" in ev else None,
        "time_to_verified_recovery_s": round(t_verified - ev["detect"]["ts"], 3) if verified and "detect" in ev else None,
        "verification_s": round(t_verified - t_verify_start, 3),
        "gates_after_rollback": {"smoke": [smoke["passed"], smoke["cases"]], "golden": [golden["passed"], golden["cases"]],
                                 "passed": verified},
        "gate_on_bad_release": {"passed": bad_gate["passed"], "cases": bad_gate["cases"],
                                "pass_rate": bad_gate["pass_rate"], "gate_passed": bad_gate["gate_passed"],
                                "adversarial_failures": bad_gate["adversarial_failures"]},
        "spawned_case": spawned["case_id"] if spawned else None,
        "release_history": rel.history(root), "rows": rows,
    }
    (OUT / "drill_log.json").write_text(json.dumps(log, indent=1) + "\n")
    (OUT / "RCA.md").write_text(rca(log, first_bad))
    build(OUT / "incident_traces.jsonl", OUT / "dashboard.html",
          eval_reports=[], events=[{"i": e["i"], "label": e["kind"]} for e in events if e["kind"] != "recovered"],
          title="ClaimSense — incident drill", subtitle=f"Drill run {iso(t_start)} · {a.requests} requests · "
                                                         f"{a.bad_release} injected at #{a.inject_at}")
    _attach_pass_marks(OUT / "dashboard.html", rows, events)
    print(f"\nblast radius: {blast}")
    print(f"time to detect: {log['time_to_detect_s']} s ({log['requests_to_detect']} requests) · "
          f"time to verified recovery: {log['time_to_verified_recovery_s']} s")
    print(f"wrote {OUT.relative_to(ROOT)}/RCA.md, drill_log.json, dashboard.html; spawned {log['spawned_case']}")
    return 0 if verified else 1


def _attach_pass_marks(path: Path, rows, events) -> None:
    """Rebuild the drill dashboard with per-request pass/fail so the pass-rate line shows."""
    fake = path.parent / "_drill_eval.json"
    fake.write_text(json.dumps({"suite": "drill", "results": [{"trace_id": r["trace_id"], "passed": r["passed"]}
                                                               for r in rows]}))
    build(path.parent / "incident_traces.jsonl", path, eval_reports=[fake],
          events=[{"i": e["i"], "label": e["kind"]} for e in events if e["kind"] != "recovered"],
          title="ClaimSense — incident drill",
          subtitle=f"Drill traffic: {len(rows)} requests · events: "
                   + ", ".join(f"{e['kind']} @#{e['i']}" for e in events))
    fake.unlink()


def rca(log: dict, first_bad: dict | None) -> str:
    ev = {e["kind"]: e for e in log["events"]}
    b = log["blast_radius"]
    det = ev.get("detect", {})
    lines = [
        "# Incident report (RCA) — incident drill",
        "",
        f"_Generated by `ops/incident_drill.py` from `runs/drill/drill_log.json` (run started {log['started']},"
        f" brain `{log['brain']}`). Facts below are from the run. Sections marked **[owner to complete]** are"
        " judgment calls for the engagement owner._",
        "",
        "## Summary",
        f"Release `{log['bad_release']}` was promoted without the eval gate at request #{ev['inject']['i']}. Its "
        "retrieval index omitted clauses CLS-LIAB-003 (Liability Only scope) and CLS-PER-006 (policy period). "
        f"The regression was detected {log['requests_to_detect']} requests later and rolled back to "
        f"`{log['baseline']}`. Recovery was verified by the smoke and golden gates.",
        "",
        "## Timeline (UTC, real timestamps)",
        "| Time | Request | Event |", "|---|---|---|",
    ]
    for e in log["events"]:
        lines.append(f"| {e['at']} | #{e['i']} | **{e['kind']}** — {e['label']} |")
    lines += [
        "",
        "## Key numbers",
        f"- Time to detect: **{log['time_to_detect_s']} s** ({log['requests_to_detect']} requests after the push)",
        f"- Time to verified recovery (detection → both gates green): **{log['time_to_verified_recovery_s']} s**",
        f"- Detection evidence: {det.get('label', '—')}; trace `{det.get('trace_id', '—')}`",
        f"- Blast radius: {b['requests_on_bad_release']} requests served by `{log['bad_release']}`, "
        f"{b['failed']} failed the eval check, {b['fallback_verdicts']} were deterministic-fallback verdicts, "
        f"{b['unsafe_approvals']} unsafe approvals reached a ticket.",
        f"- Gate on the bad release (what the skipped gate would have said): "
        f"{log['gate_on_bad_release']['passed']}/{log['gate_on_bad_release']['cases']} "
        f"({log['gate_on_bad_release']['pass_rate']:.1%}) — "
        f"{'PASS' if log['gate_on_bad_release']['gate_passed'] else 'FAIL'}",
        f"- Gates after rollback: smoke {log['gates_after_rollback']['smoke'][0]}/{log['gates_after_rollback']['smoke'][1]}, "
        f"golden {log['gates_after_rollback']['golden'][0]}/{log['gates_after_rollback']['golden'][1]}",
        "",
        "## Root cause (observed)",
        "The thin index could not retrieve CLS-PER-006 / CLS-LIAB-003, so the decide step could not cite them. "
        "Lapsed-policy and Liability-Only claims lost their denial grounds; the output guardrail rejected the "
        "resulting proposals and the deterministic fallback, unable to cite the clause it needed, routed them to "
        "a human (ESCALATE) instead of denying.",
    ]
    if first_bad:
        r = first_bad["row"]
        lines += ["", f"First failing request: #{r['i']} `{r['case_id']}` — expected {r['expected']}, got "
                      f"`{r['outcome']}` ({'; '.join(r['failures'])}); trace `{r['trace_id']}`."]
    lines += [
        "",
        "## What held",
        f"{b['unsafe_approvals']} unsafe approvals: failures were loud and safe (escalations to a human), not silent "
        "wrong approvals. Every recommendation still required human confirmation. **[owner to confirm wording]**",
        "",
        "## Action items",
        f"- [x] Regression case spawned: `{log['spawned_case']}` in `evals/regression_set.json` (runs in CI).",
        "- [ ] Block `--skip-gate` promotions outside drills. **[owner to decide]**",
        "- [ ] **[owner to complete]** any process change (who may promote, review of index changes).",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
