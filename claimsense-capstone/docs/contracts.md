# Contracts

Typed I/O between ClaimSense and the three client systems, and the API it exposes. Source of
truth: `claimsense/models.py` and `claimsense/door.py`.

## Reads (through the door; every call scope-checked and audited)

| Tool | System | Returns | Errors |
|---|---|---|---|
| `get_claim(identity, claim_id)` | claims management | `Claim` | `403 forbidden_scope`, `404 not_found` |
| `get_policy_for_claim(identity, claim_id)` | policy administration | `Policy` (only via an authorized claim) | same |
| `list_documents(identity, claim_id)` | document store | `list[Document]` (OCR text is untrusted) | same |

Malformed rows raise `ContractError` (fail closed). `policy_status` is administrative only and
never decides coverage (CLS-PER-006); the dates do.

## Writes (idempotent)

| Tool | Body | Idempotency |
|---|---|---|
| `write_ticket(identity, claim_id, kind, body, key)` | recommendation | key = `claim:release:hash(outcome, citations, rationale)`; replay returns the original ticket with `idempotent_replay: true` |
| `escalate(identity, claim_id, to_group, reason, key)` | manual escalation | caller-supplied key (CLI derives one from claim, queue and reason); durable across processes via `runs/tickets.jsonl` |

No write moves money.

## Recommendation (output)

```json
{"claim_id": "CLM-2024-1800", "outcome": "RECOMMEND_APPROVE", "verdict_source": "model",
 "rationale": "...", "citations": ["CLS-COLL-001", "CLS-DED-004", "CLS-PAY-012"], "reasons": ["..."],
 "net_payable_usd": 2700, "requires_human_confirmation": true, "confirm_role": "adjuster",
 "route_to": "adjuster", "quarantined_clauses": [], "release": "v1.0.0", "trace_id": "trc-..."}
```

- `outcome` ∈ `RECOMMEND_APPROVE | RECOMMEND_DENY | REFER_SIU | ESCALATE_HUMAN`
- `requires_human_confirmation` is always `true` (the contract rejects anything else)
- `citations` is never empty; `net_payable_usd` only on APPROVE and computed in code
- `confirm_role` is `senior-adjuster` when net payable > $25,000 (CLS-PAY-012)

## HTTP API (Lambda / `make up`)

| Route | Body | Responses |
|---|---|---|
| `POST /recommend` | `{"user_id", "claim_id", "note"?}` | 200 recommendation · 400 bad_request · 403 forbidden_scope · 404 not_found · 422 contract · 500 internal (no stack trace) |
| `GET /health` | — | `{"ok", "release", "brain"}` |

Each request prints one EMF line (`ClaimSense` namespace: `Requests`, `Errors`, `LatencyMs`).

## Model step outputs (strict, pydantic in the live brain)

| Step | Output |
|---|---|
| triage | `peril_guess ∈ {collision, comprehensive, unknown}`, `exclusion_flags: list[str]` |
| evidence | `fraud_indicators: list[str]` |
| decide | `proposed_outcome`, `rationale`, `citations`, `reasons` |
