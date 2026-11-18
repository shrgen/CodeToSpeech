"""One request handler shared by the CLI, the AgentCore entrypoint and the Lambda handler.

handle({"user_id", "claim_id", "note"?}) -> {"status": int, "body": dict}

It also prints one CloudWatch Embedded Metric Format (EMF) line per request. In Lambda and
AgentCore, stdout goes to CloudWatch Logs, and EMF lines become the metrics the dashboard
and the alarm read (namespace ClaimSense: Requests, Errors, LatencyMs).
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

from .brain import get_brain
from .door import AccessDenied, ClaimsDoor, NotFound
from .models import ContractError
from .pipeline import Pipeline
from .release import active
from .trace import Tracer

_PIPELINE: Pipeline | None = None


def pipeline() -> Pipeline:
    global _PIPELINE
    if _PIPELINE is None:
        _PIPELINE = Pipeline(ClaimsDoor(), get_brain(os.environ.get("CLAIMSENSE_BRAIN", "mock")),
                             active(), Tracer())
    return _PIPELINE


def emf(release: str, brain: str, latency_ms: float, error: bool) -> str:
    return json.dumps({
        "_aws": {"Timestamp": int(time.time() * 1000), "CloudWatchMetrics": [{
            "Namespace": "ClaimSense", "Dimensions": [["Service"]],
            "Metrics": [{"Name": "Requests", "Unit": "Count"}, {"Name": "Errors", "Unit": "Count"},
                        {"Name": "LatencyMs", "Unit": "Milliseconds"}]}]},
        "Service": "claimsense", "Release": release, "Brain": brain,
        "Requests": 1, "Errors": 1 if error else 0, "LatencyMs": round(latency_ms, 1),
    })


def handle(payload: dict[str, Any]) -> dict[str, Any]:
    p = pipeline()
    t0 = time.perf_counter()
    error = False
    try:
        user, claim = str(payload.get("user_id", "")), str(payload.get("claim_id", ""))
        if not user or not claim:
            return {"status": 400, "body": {"error": "bad_request", "message": "user_id and claim_id are required"}}
        rec = p.run(user, claim, str(payload.get("note", "")))
        error = rec.verdict_source == "deterministic_fallback"
        return {"status": 200, "body": rec.to_dict()}
    except AccessDenied as e:
        return {"status": 403, "body": e.to_error()}
    except NotFound as e:
        return {"status": 404, "body": {"error": "not_found", "message": f"no such record {e}"}}
    except ContractError as e:
        error = True
        return {"status": 422, "body": {"error": "contract", "message": str(e)}}
    except Exception as e:                                   # never leak a stack trace to a caller
        error = True
        return {"status": 500, "body": {"error": "internal", "message": type(e).__name__}}
    finally:
        print(emf(p.release.version, p.brain.name, (time.perf_counter() - t0) * 1000, error), flush=True)
