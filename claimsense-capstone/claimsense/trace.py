"""Tracing + metrics. One trace per claim run, one span per step, JSONL on disk.

The same span shape is emitted to CloudWatch (EMF) in the live deployment, so the local
dashboard and the CloudWatch dashboard read the same three numbers: error rate, call
volume, p95 latency (plus eval pass rate and cost per resolution).
"""
from __future__ import annotations

import json
import math
import random
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

# Bedrock on-demand price per 1M tokens for the default model. Verify against the AWS
# pricing page before quoting; used only for cost-per-resolution estimates.
PRICE_PER_M_INPUT = 1.00
PRICE_PER_M_OUTPUT = 5.00


class Tracer:
    def __init__(self, path: Path | None = None, simulate_model_latency: bool = False, seed: int = 7):
        self.path = path
        self.spans: list[dict[str, Any]] = []
        self.sim = simulate_model_latency
        self.rng = random.Random(seed)

    def new_trace(self) -> str:
        return "trc-" + uuid.uuid4().hex[:12]

    @contextmanager
    def span(self, trace_id: str, name: str, **attrs: Any):
        rec: dict[str, Any] = {"trace_id": trace_id, "span": name, "start": time.time(), **attrs}
        t0 = time.perf_counter()
        try:
            yield rec
        except Exception as e:
            rec["error"] = f"{type(e).__name__}: {e}"
            raise
        finally:
            rec["dur_ms"] = round((time.perf_counter() - t0) * 1000, 3)
            if self.sim and rec.get("kind") == "model":
                # labelled simulation of a hosted model call (lognormal, median ~700 ms)
                rec["simulated_model_ms"] = round(self.rng.lognormvariate(math.log(700), 0.45), 1)
            self.spans.append(rec)
            if self.path:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a") as f:
                    f.write(json.dumps(rec) + "\n")


def cost_usd(input_tokens: int, output_tokens: int) -> float:
    return input_tokens / 1e6 * PRICE_PER_M_INPUT + output_tokens / 1e6 * PRICE_PER_M_OUTPUT


def load_spans(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def percentile(xs: list[float], q: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    k = (len(s) - 1) * q / 100
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] if lo == hi else s[lo] + (s[hi] - s[lo]) * (k - lo)


def summarize(spans: list[dict[str, Any]]) -> dict[str, Any]:
    """Roll spans up to per-request rows and the dashboard numbers."""
    runs = [s for s in spans if s["span"] == "claim.run"]
    lat = [s["dur_ms"] + s.get("simulated_total_model_ms", 0) for s in runs]
    errors = [s for s in runs if is_error(s)]
    tok_in = sum(s.get("input_tokens", 0) for s in runs)
    tok_out = sum(s.get("output_tokens", 0) for s in runs)
    simulated = any(s.get("simulated_total_model_ms") for s in runs)
    return {
        "call_volume": len(runs),
        "error_count": len(errors),
        "error_rate": round(len(errors) / len(runs), 4) if runs else 0.0,
        "p50_ms": round(percentile(lat, 50), 1),
        "p95_ms": round(percentile(lat, 95), 1),
        "cost_per_resolution_usd": round(cost_usd(tok_in, tok_out) / len(runs), 6) if runs else 0.0,
        "latency_includes_simulated_model_time": simulated,
        "outcomes": _count(r.get("outcome") for r in runs),
        "verdict_sources": _count(r.get("verdict_source") for r in runs),
    }


def is_error(run_span: dict[str, Any]) -> bool:
    """An error is a request that raised, or whose verdict came from the deterministic fallback.
    A scope refusal (AccessDenied -> 403) is the door working, not a failure, and is not counted;
    this matches the Errors metric the live service emits (claimsense/service.py)."""
    err = run_span.get("error") or ""
    if err.startswith("AccessDenied"):
        return False
    return bool(err) or run_span.get("verdict_source") == "deterministic_fallback"


def _count(it) -> dict[str, int]:
    out: dict[str, int] = {}
    for x in it:
        out[str(x)] = out.get(str(x), 0) + 1
    return out
