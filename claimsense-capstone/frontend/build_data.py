"""Bake real pipeline output into frontend/data.js so the portal runs from file:// or S3.

Every recommendation shown in the portal comes from running the actual pipeline (mock brain,
active release) here; nothing is hand-written. Re-run after any change:
    python3 frontend/build_data.py
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from claimsense.brain import get_brain  # noqa: E402
from claimsense.door import AccessDenied, AuditLog, ClaimsDoor  # noqa: E402
from claimsense.pipeline import Pipeline  # noqa: E402
from claimsense.release import active  # noqa: E402
from claimsense.retrieval import load_corpus  # noqa: E402
from claimsense.trace import Tracer, summarize  # noqa: E402

FE = ROOT / "frontend"


def main() -> None:
    seed = json.loads((ROOT / "claimsense" / "data" / "seed.json").read_text(encoding="utf-8"))
    users = json.loads((ROOT / "claimsense" / "data" / "users.json").read_text(encoding="utf-8"))
    door = ClaimsDoor(audit=AuditLog())
    rel = active()
    tracer = Tracer(simulate_model_latency=True)
    pipe = Pipeline(door, get_brain("mock"), rel, tracer)

    access = {cid: {u: door.can_read(door.identity(u), row)[0] for u in users} for cid, row in door._claims.items()}
    recs = {}
    for cid, row in door._claims.items():
        reader = row["assigned_adjuster"] if access[cid].get(row["assigned_adjuster"]) else "bob"
        recs[cid] = dict(pipe.run(reader, cid).to_dict(), run_as=reader)
    # a few real out-of-scope attempts, so the audit tab shows denials
    for user, cid in [("alice", "CLM-2024-2019"), ("david", "CLM-2024-1800"), ("carol", "CLM-2024-1800")]:
        try:
            door.bundle(door.identity(user), cid)
        except AccessDenied:
            pass

    def load(p):
        p = ROOT / p
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    ev = load("runs/eval_golden_mock_v1.0.0.json")
    cases = {c["case_id"]: c for c in json.loads((ROOT / "evals" / "golden_set.json").read_text(encoding="utf-8"))["cases"]}
    evals = None
    if ev:
        evals = {k: ev[k] for k in ("suite", "brain", "release", "cases", "passed", "pass_rate", "gate_passed",
                                    "adversarial_failures", "by_family", "verdict_sources", "finished", "min_pass")}
        evals["rows"] = [{"id": r["case_id"], "family": r["family"], "sub": r["subfamily"], "passed": r["passed"],
                          "outcome": r["outcome"], "expected": r["expected"], "source": r["verdict_source"],
                          "failures": r["failures"], "user": cases[r["case_id"]]["user_id"],
                          "claim": cases[r["case_id"]]["claim_id"], "why": cases[r["case_id"]]["rationale"],
                          "note": cases[r["case_id"]].get("note", "")} for r in ev["results"]]
    drill = load("runs/drill/drill_log.json")
    if drill:
        drill = {k: drill[k] for k in ("started", "events", "blast_radius", "time_to_detect_s", "requests_to_detect",
                                       "time_to_verified_recovery_s", "gates_after_rollback", "gate_on_bad_release",
                                       "spawned_case", "bad_release", "baseline", "requests")}
    ops = summarize([json.loads(l) for l in (ROOT / "runs/traces/golden_mock_v1.0.0.jsonl").read_text(encoding="utf-8").splitlines()]) \
        if (ROOT / "runs/traces/golden_mock_v1.0.0.jsonl").exists() else None

    data = {
        "built": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "release": asdict(rel), "client": seed.get("client"),
        "users": users, "claims": seed["claims"], "policies": seed["policies"], "documents": seed["documents"],
        "access": access, "recommendations": recs,
        "clauses": [{"id": c.clause_id, "title": c.title, "text": c.text} for c in load_corpus()],
        "audit": [r.__dict__ for r in door.audit.rows], "evals": evals, "drill": drill, "ops": ops,
    }
    (FE / "data.js").write_text("window.CLAIMSENSE = " + json.dumps(data, separators=(",", ":")) + ";\n", encoding="utf-8")
    for src, dst in [("ops/dashboard.html", "ops.html"), ("runs/drill/dashboard.html", "drill.html")]:
        if (ROOT / src).exists():
            shutil.copy(ROOT / src, FE / dst)
    print(f"wrote frontend/data.js ({(FE / 'data.js').stat().st_size // 1024} KB): {len(recs)} recommendations, "
          f"{len(data['audit'])} audit rows, evals={'yes' if evals else 'no'}, drill={'yes' if drill else 'no'}")


if __name__ == "__main__":
    main()
