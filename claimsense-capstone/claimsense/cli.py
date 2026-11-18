"""claimsense — command line for operators.

  python3 -m claimsense run --user alice --claim CLM-2024-1800 [--note ...] [--brain mock|bedrock]
  python3 -m claimsense eval --suite golden --min-pass 0.95 --brain mock [--release v1.0.0]
  python3 -m claimsense release show | promote VERSION --actor A --reason R | rollback --actor A --reason R
  python3 -m claimsense escalate --user bob --claim CLM-2024-1873 --to siu --reason "..."
  python3 -m claimsense user add --id frank --name "Frank Li" --group adjuster
  python3 -m claimsense corpus check
  python3 -m claimsense dashboard [--traces runs/traces/...jsonl] [--out ops/dashboard.html]
  python3 -m claimsense serve [--port 8080]

Exit codes: 0 ok · 1 gate failed / check failed · 2 usage or access error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import uuid
from pathlib import Path

from . import release as rel
from .brain import get_brain
from .door import DATA, AccessDenied, AuditLog, ClaimsDoor, NotFound, load_users
from .evalsuite import format_report, load_suite, run_suite
from .models import ContractError
from .pipeline import Pipeline
from .retrieval import CLAUSE_ID, CORPUS_DIR, PolicyIndex, injection_hits, load_corpus
from .trace import Tracer, load_spans, summarize

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"


def _release(version: str | None) -> rel.Release:
    return rel.Release.load(version) if version else rel.active()


def cmd_run(a) -> int:
    door = ClaimsDoor(audit=AuditLog(RUNS / "audit.jsonl"), ticket_log=RUNS / "tickets.jsonl")
    tracer = Tracer(RUNS / "traces" / "cli.jsonl")
    p = Pipeline(door, get_brain(a.brain), _release(a.release), tracer)
    try:
        rec = p.run(a.user, a.claim, a.note or "")
    except AccessDenied as e:
        print(json.dumps({"status": 403, **e.to_error()}, indent=1))
        return 2
    except NotFound as e:
        print(json.dumps({"status": 404, "error": "not_found", "message": str(e)}))
        return 2
    print(json.dumps(rec.to_dict(), indent=1))
    return 0


def cmd_eval(a) -> int:
    release = _release(a.release)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    name = f"{a.suite}_{a.brain}_{release.version}"
    trace_path = RUNS / "traces" / f"{name}.jsonl"
    if trace_path.exists():
        trace_path.unlink()                         # one trace file per (suite, brain, release): latest run
    rep = run_suite(load_suite(a.suite), get_brain(a.brain), release,
                    Tracer(trace_path, simulate_model_latency=a.brain == "mock"), a.min_pass)
    rep["trace_file"] = str(trace_path.relative_to(ROOT))
    rep["run_id"] = f"{name}_{stamp}"
    out = Path(a.out) if a.out else RUNS / f"eval_{name}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, indent=1) + "\n")
    print(format_report(rep))
    print(f"report: {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}")
    return 0 if rep["gate_passed"] else 1


def cmd_release(a) -> int:
    if a.action == "show":
        r = rel.active()
        print(json.dumps({"active": r.version, **r.__dict__}, indent=1))
        print("history:")
        for h in rel.history()[-10:]:
            print(f"  {h['ts']}  {h['version']:<8} {h['actor']:<10} {h['reason']}")
        return 0
    if not a.actor or not a.reason:
        print("promote/rollback need --actor and --reason (they go in HISTORY.log)", file=sys.stderr)
        return 2
    if a.action == "promote":
        if not a.version:
            print("promote needs a VERSION", file=sys.stderr)
            return 2
        if not a.skip_gate:
            rep = run_suite(load_suite("golden"), get_brain("mock"), rel.Release.load(a.version), min_pass=0.95)
            print(format_report(rep).splitlines()[-1])
            if not rep["gate_passed"]:
                print(f"refusing to promote {a.version}: golden gate failed", file=sys.stderr)
                return 1
        rel.promote(a.version, a.actor, a.reason + (" [gate skipped]" if a.skip_gate else " [gate passed]"))
        print(f"active release: {rel.active_version()}")
        return 0
    if a.action == "rollback":
        v = rel.rollback(a.actor, a.reason)
        print(f"rolled back; active release: {v}")
        return 0
    return 2


def cmd_escalate(a) -> int:
    door = ClaimsDoor(audit=AuditLog(RUNS / "audit.jsonl"), ticket_log=RUNS / "tickets.jsonl")
    key = a.key or f"esc:{a.claim}:{a.to}:{uuid.uuid5(uuid.NAMESPACE_URL, a.reason.strip()).hex[:12]}"
    try:
        t = door.escalate(door.identity(a.user), a.claim, a.to, a.reason, key)
    except AccessDenied as e:
        print(json.dumps({"status": 403, **e.to_error()}, indent=1))
        return 2
    except (ContractError, NotFound) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(json.dumps(t, indent=1))
    return 0


def cmd_user(a) -> int:
    path = DATA / "users.json"
    users = load_users(path)
    if a.action == "list":
        for u, info in users.items():
            print(f"{u:<8} {info['group']:<22} {info.get('name', '')}")
        return 0
    if not re.fullmatch(r"[a-z][a-z0-9_-]{1,31}", a.id or ""):
        print("--id must be lowercase letters/digits (2-32 chars)", file=sys.stderr)
        return 2
    if a.id in users:
        print(f"user {a.id!r} already exists ({users[a.id]['group']})", file=sys.stderr)
        return 2
    if a.group not in ClaimsDoor.GROUPS:
        print(f"--group must be one of {sorted(ClaimsDoor.GROUPS)}", file=sys.stderr)
        return 2
    users[a.id] = {"group": a.group, "name": a.name}
    path.write_text(json.dumps(users, indent=1) + "\n")
    ClaimsDoor()                                     # re-validate the whole user file
    with (RUNS / "admin.log").open("a") as f:
        f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "action": "user.add",
                            "user": a.id, "group": a.group, "by": a.actor}) + "\n")
    print(f"added {a.id} ({a.group}); they can read: "
          f"{len(ClaimsDoor().visible_claims(ClaimsDoor().identity(a.id)))} claims")
    return 0


def corpus_problems(directory: Path = CORPUS_DIR) -> tuple[list[str], list[str]]:
    problems, info = [], []
    seen: dict[str, str] = {}
    for f in sorted(directory.glob("*.md")):
        first = (f.read_text().strip().splitlines() or [""])[0]
        m = CLAUSE_ID.match(first)
        if not m:
            problems.append(f"{f.name}: first line must be '# CLS-XXX-NNN — Title'")
            continue
        cid = m.group(1)
        if not f.name.startswith(cid):
            problems.append(f"{f.name}: file name does not start with its clause id {cid}")
        if cid in seen:
            problems.append(f"{cid} defined twice ({seen[cid]}, {f.name})")
        seen[cid] = f.name
        hits = injection_hits(f.read_text())
        if hits:
            problems.append(f"{cid}: instruction-like text would be quarantined ({hits[0]})")
    code = " ".join(p.read_text() for p in (ROOT / "claimsense").glob("*.py"))
    for cid in sorted(set(re.findall(r"CLS-[A-Z]+-\d{3}", code))):
        if cid not in seen:
            problems.append(f"{cid} is referenced by the code but missing from the corpus")
    idx = PolicyIndex(load_corpus(directory))
    info.append(f"{len(seen)} clauses, {len(idx.ids())} indexed, {len(idx.quarantined)} quarantined")
    return problems, info


def cmd_corpus(a) -> int:
    problems, info = corpus_problems()
    for i in info:
        print(i)
    for p in problems:
        print("PROBLEM:", p)
    if problems:
        return 1
    print("corpus OK — next: run the golden gate before promoting a release")
    return 0


def cmd_dashboard(a) -> int:
    from .dashboard import build
    traces = Path(a.traces) if a.traces else RUNS / "traces" / "golden_mock_v1.0.0.jsonl"
    out = Path(a.out) if a.out else ROOT / "ops" / "dashboard.html"
    build(traces, out, eval_reports=sorted(RUNS.glob("eval_*.json")))
    s = summarize(load_spans(traces))
    print(f"dashboard: {out}  (calls={s['call_volume']} error_rate={s['error_rate']:.1%} p95={s['p95_ms']} ms)")
    return 0


def cmd_serve(a) -> int:
    from .server import serve
    serve(a.host, a.port)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="claimsense", description="ClaimSense operator CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="recommend on one claim")
    r.add_argument("--user", required=True)
    r.add_argument("--claim", required=True)
    r.add_argument("--note", default="")
    r.add_argument("--brain", default="mock", choices=["mock", "bedrock"])
    r.add_argument("--release")
    r.set_defaults(fn=cmd_run)

    e = sub.add_parser("eval", help="run an eval suite and apply the gate")
    e.add_argument("--suite", default="golden")
    e.add_argument("--min-pass", type=float, default=0.95)
    e.add_argument("--brain", default="mock", choices=["mock", "bedrock"])
    e.add_argument("--release")
    e.add_argument("--out")
    e.set_defaults(fn=cmd_eval)

    rl = sub.add_parser("release", help="show / promote / rollback")
    rl.add_argument("action", choices=["show", "promote", "rollback"])
    rl.add_argument("version", nargs="?")
    rl.add_argument("--actor")
    rl.add_argument("--reason")
    rl.add_argument("--skip-gate", action="store_true", help="promote without the golden gate (logged)")
    rl.set_defaults(fn=cmd_release)

    es = sub.add_parser("escalate", help="manually escalate a flagged claim")
    es.add_argument("--user", required=True)
    es.add_argument("--claim", required=True)
    es.add_argument("--to", required=True, help="siu | senior-adjuster | fraud-investigator | total-loss-appraiser")
    es.add_argument("--reason", required=True)
    es.add_argument("--key", help="idempotency key (default: derived from claim, queue and reason)")
    es.set_defaults(fn=cmd_escalate)

    u = sub.add_parser("user", help="add or list users")
    u.add_argument("action", choices=["add", "list"])
    u.add_argument("--id")
    u.add_argument("--name", default="")
    u.add_argument("--group")
    u.add_argument("--actor", default="operator")
    u.set_defaults(fn=cmd_user)

    c = sub.add_parser("corpus", help="validate the policy corpus")
    c.add_argument("action", choices=["check"])
    c.set_defaults(fn=cmd_corpus)

    d = sub.add_parser("dashboard", help="build the ops dashboard HTML from traces")
    d.add_argument("--traces")
    d.add_argument("--out")
    d.set_defaults(fn=cmd_dashboard)

    sv = sub.add_parser("serve", help="serve the portal and the /recommend API locally")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8080)
    sv.set_defaults(fn=cmd_serve)

    a = ap.parse_args(argv)
    return a.fn(a)
