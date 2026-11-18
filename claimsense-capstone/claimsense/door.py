"""The governed door: the ONLY way agents reach the three client systems.

Claims management, policy administration and the document store are read through typed
tools here. Every call runs as a named Identity, is scope-checked in plain code, and writes
an audit row (denials included). The LLM is never the access boundary.

Writes (recommendation tickets, manual escalations) are idempotent: same key -> same ticket.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import Claim, ClaimBundle, ContractError, Document, Identity, Policy

DATA = Path(__file__).parent / "data"

FRAUD_ACCESS_THRESHOLD = 0.5      # fraud-investigator may read claims at/above this score
TOTAL_LOSS_RATIO = 0.75           # CLS-TL-005


class AccessDenied(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

    def to_error(self) -> dict[str, str]:
        return {"error": self.code, "message": self.message,
                "hint": "This access was denied and logged in the audit trail."}


class NotFound(Exception):
    pass


@dataclass
class AuditRow:
    ts: float
    acting_user: str
    group: str
    action: str
    resource: str
    decision: str
    reason: str


class AuditLog:
    """Append-only. Optionally mirrored to a JSONL file."""

    def __init__(self, path: Path | None = None):
        self.rows: list[AuditRow] = []
        self.path = path
        self._lock = threading.Lock()

    def write(self, row: AuditRow) -> None:
        with self._lock:
            self.rows.append(row)
            if self.path:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a") as f:
                    f.write(json.dumps(row.__dict__) + "\n")


def load_users(path: Path | None = None) -> dict[str, dict[str, str]]:
    return json.loads((path or DATA / "users.json").read_text())


class ClaimsDoor:
    """Typed, scope-checked tools over the three systems of record."""

    GROUPS = {"adjuster", "senior-adjuster", "fraud-investigator", "total-loss-appraiser"}

    def __init__(self, seed: dict[str, Any] | None = None, audit: AuditLog | None = None,
                 users: dict[str, dict[str, str]] | None = None, ticket_log: Path | None = None):
        seed = seed or json.loads((DATA / "seed.json").read_text())
        self.users = users if users is not None else load_users()
        for u, info in self.users.items():
            if info.get("group") not in self.GROUPS:
                raise ContractError(f"user {u} has unknown group {info.get('group')!r}")
        self._claims = {r["claim_id"]: r for r in seed["claims"]}
        self._policies = {r["policy_id"]: r for r in seed["policies"]}
        self._docs: dict[str, list[dict[str, Any]]] = {}
        for d in seed["documents"]:
            self._docs.setdefault(d["claim_id"], []).append(d)
        self.audit = audit or AuditLog()
        self._tickets: dict[str, dict[str, Any]] = {}
        self._ticket_seq = 0
        self._lock = threading.Lock()
        # optional durable ticket log: replays keep idempotency across processes (CLI runs)
        self.ticket_log = ticket_log
        if ticket_log and ticket_log.exists():
            for line in ticket_log.read_text().splitlines():
                if line.strip():
                    rec = json.loads(line)
                    self._tickets[rec["idempotency_key"]] = rec["ticket"]
                    self._ticket_seq = max(self._ticket_seq, int(rec["ticket"]["ticket_id"].split("-")[1]))

    # ── identity ────────────────────────────────────────────────────────────
    def identity(self, user_id: str) -> Identity:
        """The on-behalf-of exchange in miniature: a known user in, a scoped identity out."""
        info = self.users.get(user_id)
        if not info:
            raise AccessDenied("unknown_user", f"No seat for user {user_id!r}.")
        return Identity(user_id, info["group"])

    # ── scope gate (plain code, writes the audit row BEFORE deciding) ───────
    def can_read(self, ident: Identity, claim_row: dict[str, Any]) -> tuple[bool, str]:
        g = ident.group
        if g == "senior-adjuster":
            return True, "Senior adjusters may read every claim."
        if g == "adjuster":
            if claim_row["assigned_adjuster"] == ident.user_id:
                return True, "Assigned adjuster."
            return False, f"Claim is assigned to {claim_row['assigned_adjuster']}, not {ident.user_id}."
        if g == "fraud-investigator":
            score = float(claim_row["fraud_risk_score"])
            if score >= FRAUD_ACCESS_THRESHOLD:
                return True, f"Fraud score {score:.2f} meets the investigator threshold."
            return False, f"Fraud score {score:.2f} is below the fraud-investigator access threshold."
        if g == "total-loss-appraiser":
            ratio = int(claim_row["repair_estimate_usd"]) / max(int(claim_row["vehicle_acv_usd"]), 1)
            if claim_row["claim_status"] == "Escalated" or ratio >= TOTAL_LOSS_RATIO:
                return True, "Escalated or total-loss candidate."
            return False, "Not escalated and below the total-loss threshold."
        return False, "Unknown group."

    def _authorize(self, ident: Identity, action: str, claim_id: str) -> dict[str, Any]:
        row = self._claims.get(claim_id)
        if row is None:
            self.audit.write(AuditRow(time.time(), ident.user_id, ident.group, action, claim_id,
                                      "not_found", "no such claim"))
            raise NotFound(claim_id)
        ok, reason = self.can_read(ident, row)
        self.audit.write(AuditRow(time.time(), ident.user_id, ident.group, action, claim_id,
                                  "allow" if ok else "deny", reason))
        if not ok:
            raise AccessDenied("forbidden_scope", reason)
        return row

    # ── typed read tools (one per system of record) ─────────────────────────
    def get_claim(self, ident: Identity, claim_id: str) -> Claim:
        """Claims management system."""
        return Claim.from_row(self._authorize(ident, "claims.get", claim_id))

    def get_policy_for_claim(self, ident: Identity, claim_id: str) -> Policy:
        """Policy administration system. Reachable only through an authorized claim."""
        row = self._authorize(ident, "policy.get", claim_id)
        p = self._policies.get(row["policy_id"])
        if p is None:
            raise NotFound(row["policy_id"])
        return Policy.from_row(p)

    def list_documents(self, ident: Identity, claim_id: str) -> list[Document]:
        """Document store."""
        self._authorize(ident, "documents.list", claim_id)
        return [Document.from_row(d) for d in self._docs.get(claim_id, [])]

    def bundle(self, ident: Identity, claim_id: str, request_note: str = "") -> ClaimBundle:
        return ClaimBundle(self.get_claim(ident, claim_id), self.get_policy_for_claim(ident, claim_id),
                           self.list_documents(ident, claim_id), request_note)

    def visible_claims(self, ident: Identity) -> list[str]:
        return [cid for cid, row in self._claims.items() if self.can_read(ident, row)[0]]

    # ── idempotent writes ───────────────────────────────────────────────────
    def write_ticket(self, ident: Identity, claim_id: str, kind: str, body: dict[str, Any],
                     idempotency_key: str) -> dict[str, Any]:
        """Post a recommendation / escalation note on a claim. Never moves money."""
        if not idempotency_key:
            raise ContractError("writes require an idempotency key")
        self._authorize(ident, f"ticket.{kind}", claim_id)
        with self._lock:
            if idempotency_key in self._tickets:
                t = dict(self._tickets[idempotency_key])
                t["idempotent_replay"] = True
                return t
            self._ticket_seq += 1
            t = {"ticket_id": f"TKT-{self._ticket_seq:06d}", "claim_id": claim_id, "kind": kind,
                 "author": ident.user_id, "body": body, "created": time.time(),
                 "body_sha256": hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()}
            self._tickets[idempotency_key] = t
            if self.ticket_log:
                self.ticket_log.parent.mkdir(parents=True, exist_ok=True)
                with self.ticket_log.open("a") as f:
                    f.write(json.dumps({"idempotency_key": idempotency_key, "ticket": t}) + "\n")
            return dict(t)

    def escalate(self, ident: Identity, claim_id: str, to_group: str, reason: str,
                 idempotency_key: str) -> dict[str, Any]:
        """Manual escalation of a flagged claim to a specialist queue."""
        if to_group not in self.GROUPS - {"adjuster"} | {"siu"}:
            raise ContractError(f"cannot escalate to {to_group!r}")
        if not reason.strip():
            raise ContractError("an escalation needs a written reason")
        return self.write_ticket(ident, claim_id, "escalation",
                                 {"to": to_group, "reason": reason.strip()}, idempotency_key)

    # ── test/eval hooks (not exposed to agents) ─────────────────────────────
    def _put_claim_row(self, row: dict[str, Any], policy: dict[str, Any] | None = None,
                       docs: list[dict[str, Any]] | None = None) -> None:
        self._claims[row["claim_id"]] = row
        if policy is not None:
            self._policies[policy["policy_id"]] = policy
        if docs is not None:
            self._docs[row["claim_id"]] = docs
