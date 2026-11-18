"""AWS Lambda handler behind an API Gateway HTTP API (payload format 2.0).

POST /recommend  body {"user_id", "claim_id", "note"?} -> the recommendation (or 403/404).
GET  /health     -> {"ok": true, "release": ...}
"""
from __future__ import annotations

import json

from claimsense.service import handle, pipeline

CORS = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "content-type",
        "Access-Control-Allow-Methods": "GET,POST,OPTIONS"}


def _resp(status: int, body) -> dict:
    return {"statusCode": status, "headers": {"content-type": "application/json", **CORS},
            "body": json.dumps(body)}


def handler(event, context):
    method = (event.get("requestContext", {}).get("http", {}).get("method") or "POST").upper()
    path = event.get("rawPath", "/recommend")
    if method == "OPTIONS":
        return _resp(204, {})
    if method == "GET" and path.endswith("/health"):
        p = pipeline()
        return _resp(200, {"ok": True, "release": p.release.version, "brain": p.brain.name})
    try:
        payload = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _resp(400, {"error": "bad_request", "message": "body must be JSON"})
    out = handle(payload)
    return _resp(out["status"], out["body"])
