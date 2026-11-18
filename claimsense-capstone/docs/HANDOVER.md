# Handover pack — ClaimSense

Everything AutoSure needs to run, verify and change ClaimSense without the builders.

## Start here
| | |
|---|---|
| Run it locally | `make up` → http://127.0.0.1:8080 |
| Prove it works | `make verify` (tests + smoke + regression) and `make golden` (150-case gate) |
| Something broke | `docs/RUNBOOK.md` |

## Engagement artefacts by week
| Week | Artefact | Location |
|---|---|---|
| W1 | Engagement charter (3 systems + integration points) | **[owner: add link]** |
| W1 | Stakeholder map + RACI | **[owner: add link]** |
| W1 | Success criteria (4, quantified) | **[owner: add link]** |
| W1 | DECISIONS.md (≥3 dated decisions) | **[owner: add link]**; Week 5 draft additions in `docs/DECISIONS.md` |
| W1 | 20 initial eval cases | the 20 `BASE-*` cases in `evals/golden_set.json` |
| W2 | Statement of work | **[owner: add link]** |
| W2 | Architecture diagram (deterministic/model boundary) | `docs/architecture.md` (+ owner's W2 diagram: **[link]**) |
| W2 | Pricing model, risk register | **[owner: add links]** |
| W2 | Typed I/O contracts incl. idempotency | `docs/contracts.md` |
| W3 | Agents (OpenAI Agents SDK, typed outputs) | `claimsense/live/sdk_agents.py` |
| W3 | Container + single-command start | `Dockerfile`, `make up` |
| W3 | Retrieval with clause-id citations | `claimsense/retrieval.py`, `claimsense/data/corpus/` |
| W3 | CI gate blocking image push | `.github/workflows/claimsense-eval-gate.yml` |
| W5 | 150-case eval suite + gate | `evals/`, `claimsense/evalsuite.py`, `runs/eval_golden_mock_v1.0.0.json` |
| W5 | Second grader (promptfoo) | `evals/promptfoo-golden.yaml`, `evals/promptfoo.yaml`, `runs/promptfoo_golden_agreement.json` |
| W5 | Ops dashboard + one alarm | `ops/dashboard.html`, `ops/cloudwatch/observability.yaml` |
| W5 | Incident drill + report | `ops/incident_drill.py`, `runs/drill/`, `docs/INCIDENT_REPORT.md` |
| W5 | Runbook (4 procedures) | `docs/RUNBOOK.md` |
| W5 | Observation document | `docs/OBSERVATION.md` |
| W5 | Client demo | `docs/DEMO_SCRIPT.md`, portal (`frontend/`) |
| W5 | Deployed portal URL + demo recording | **[owner: add after deploy]** |

## What to watch monthly
- Golden gate on the active release (`make golden`), and the live-model gate once enabled.
- Error rate and p95 on the CloudWatch dashboard `claimsense-ops`; alarm history.
- `runs/audit.jsonl` denials: repeated out-of-scope attempts by one user are worth a question.
- Fallback share: a rising share of deterministic-fallback verdicts on normal traffic means the
  model and the guardrail disagree more often — investigate before it pages.

## Deploy / teardown
`deploy/deploy_frontend.sh <bucket>` and `deploy/deploy_api.sh <artifact-bucket> [mock|bedrock]`.
Teardown: delete stacks `claimsense-portal`, `claimsense-api`, `claimsense-observability`
(empty the portal bucket first). Set an AWS Budgets alert before any live run.
