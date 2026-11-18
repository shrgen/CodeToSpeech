# Architecture

ClaimSense makes **one first-decision recommendation for one claim**, which a licensed human
confirms. The line between what the model decides and what code decides is the core of the
design.

```
 adjuster / portal / CLI / Lambda / AgentCore
            │  (user_id, claim_id, note)
            ▼
 ┌──────────────────────── governed door (door.py) ────────────────────────┐   CODE
 │ identity → RBAC scope check → audit row (denials too) → typed reads of  │
 │ claims mgmt · policy admin · document store      idempotent ticket writes│
 └─────────────────────────────────────────────────────────────────────────┘
            ▼
   input quarantine (retrieval.py): instruction-like OCR text / notes /           CODE
   corpus clauses removed before any model sees them
            ▼
   triage  ── peril guess, exclusion flags ──────────────────────────────────    MODEL
            ▼
   facts (rules.py): policy period, coverage, deductible, net payable,            CODE
   total-loss ratio, missing docs, injury inconsistency, high value
            ▼
   evidence ── fraud indicators from the narrative ──────────────────────────    MODEL
            ▼
   retrieval (BM25 over 12 clauses, clause ids) ─────────────────────────────    CODE
            ▼
   decide  ── proposed outcome, rationale, citations ────────────────────────    MODEL
            ▼
   output guardrail (guardrail.py): citations ⊆ retrieved and not quarantined,   CODE
   hard constraints, money only from code, no payment-authority language,
   no other record mentioned  ──fail──▶ deterministic fallback (rules.rule_outcome;
            │ pass                        never approves on its own)
            ▼
   recommendation (verdict_source = model | deterministic_fallback),             CODE
   route + confirming role, idempotent ticket → HUMAN CONFIRMS
```

**Model decides:** peril for unknown incident types, exclusion findings, narrative fraud
indicators, the proposed outcome and its wording.
**Code decides:** who may see what, dates, money, thresholds, document readiness, whether the
model's proposal is accepted, routing, and every write.

| Module | Role |
|---|---|
| `models.py` | typed contracts; `validate()` fails closed |
| `door.py` | the only access path to the three systems; RBAC, audit, idempotent writes |
| `rules.py` | deterministic facts, hard constraints, fallback decision, routing |
| `retrieval.py` | clause index + input quarantine |
| `brain.py`, `live/sdk_agents.py` | MockBrain ($0, deliberately naive) and BedrockBrain (OpenAI Agents SDK + LiteLLM, Claude Haiku 4.5) |
| `guardrail.py` | output checks; any violation → fallback |
| `pipeline.py` | the flow above, one trace per run |
| `trace.py`, `dashboard.py`, `service.py` | spans, metrics, EMF for CloudWatch |
| `release.py` | pinned releases, promote (gated), rollback |
| `evalsuite.py`, `evals/` | execution-graded golden gate, smoke, regression; promptfoo graders |

**Deployment:** portal on S3 + CloudFront (`deploy/frontend.yaml`); API as Lambda + HTTP API
(`deploy/api.yaml`) or AgentCore Runtime (`claimsense/live/agentcore_app.py`); CloudWatch
dashboard + one alarm (`ops/cloudwatch/observability.yaml`). Locally: `make up`.
