# ClaimSense — session context (2026-11-18)

Handoff from the Claude Code session that finished the Week 5 build. Read this with
`CLAUDE.md` (the planning-session context) before continuing.

- **Repo / branch:** `shrgen/CodeToSpeech`, branch `claude/claims-since-project-tlbgoc`
  (pushed). ClaimSense lives in `claimsense-capstone/`; the repo root also holds an unrelated
  small tool (`src/codetospeech/`, reads source code aloud).
- **Course:** Interview Kickstart FDE capstone. Instructor reference repo:
  `new-programs-ik/ik-fde-codebase` (public). Do **not** copy its `codebase/agent/` — graders
  diff for it.

## 1. What ClaimSense is
First-decision co-pilot for AutoSure Insurance claim adjusters (synthetic data). For one claim:
governed door (RBAC + audit) → input quarantine → triage (model) → facts (code) → evidence
(model) → clause retrieval → decide (model) → output guardrail → recommendation that a licensed
human confirms. Four outcomes: RECOMMEND_APPROVE / RECOMMEND_DENY / REFER_SIU / ESCALATE_HUMAN.
Never moves money (CLS-PAY-012). Money, dates, access and thresholds are computed in code, never
by the model (e.g. CLM-2024-1800: min($3,200 estimate, $24,500 ACV) − $500 deductible = $2,700).

## 2. What was built this session
Started from the planning-session WIP zip (core pipeline, data, releases), then added:

| Area | Files |
|---|---|
| Live brain (Agents SDK + LiteLLM `bedrock/converse/…`, Claude Haiku 4.5) | `claimsense/live/sdk_agents.py`, `agentcore_app.py`, `lambda_handler.py`, `claimsense/service.py` (EMF metrics) |
| CLI | `python3 -m claimsense run / eval / release / escalate / user / corpus / dashboard / serve` |
| 150-case golden set + gate | `evals/build_golden.py` → `golden_set.json` (20 base, 100 variants, 30 ADV), `smoke_set.json`, `regression_set.json`; `claimsense/evalsuite.py` |
| Second grader | `evals/promptfoo-golden.yaml` (agreement runner), `evals/promptfoo.yaml` (rubric, 2 standard + 4 adversarial) |
| Ops | `claimsense/dashboard.py` → `ops/dashboard.html`; `ops/incident_drill.py`; `ops/ablation.py`; `ops/cloudwatch/observability.yaml` (dashboard + error-rate > 5% alarm) |
| Portal | `frontend/` (view-as RBAC, recommendations + citations, role-gated confirm, evals, ops, audit, live-API mode); `frontend/build_data.py` |
| Packaging / CI | `Makefile`, `Dockerfile` (gate runs during build), `claimsense/server.py` (`make up`), `.github/workflows/claimsense-eval-gate.yml` |
| Deploy | `deploy/frontend.yaml` (S3 + CloudFront), `deploy/api.yaml` (Lambda + HTTP API), `deploy/*.sh` |
| Tests | `tests/` — 49 unit tests |
| Docs | `docs/` RUNBOOK, INCIDENT_REPORT, OBSERVATION, HANDOVER, DECISIONS (draft), DEMO_SCRIPT, architecture, contracts; `README.md` |

## 3. Verified results (mock brain, committed under `runs/`)
| Check | Result |
|---|---|
| Golden gate v1.0.0 | 150/150, adversarial 30/30, GATE PASSED |
| Golden gate v1.1.0 (drill release) | 118/150 (78.7%), GATE FAILED; all 32 failures DENY→ESCALATE, 0 unsafe approvals |
| promptfoo agreement | 150/150 |
| Incident drill | injected #30, detected #44 (3.55 s), rolled back #45, verified recovery 0.404 s, 0 unsafe approvals, regression case spawned |
| Ablation | guardrail only: 30/30 ADV; no guards: 7/30 (3 = door 403s, 4 = cases the mock can't exercise) |
| RBAC vs portal oracle | 0 mismatches (alice 6, bob 20, carol 3, eve 4 claims) |
| Unit tests | 49 pass |
| Lambda handler (local) | 200 / 403 / 400 paths correct, one EMF line per request |

Not verified here: Docker build (no daemon; build steps simulated), AWS deploys, any live
Bedrock call.

## 4. Findings worth keeping
- Golden traffic runs a 10.7% error rate by design (adversarial cases are rejected), so the
  production alarm must watch normal traffic only.
- 403 scope refusals are not errors (fixed in `trace.is_error`, matches the EMF metric).
- The adversarial veto also fires on safe-but-wrong regressions (v1.1.0).
- Mock latency includes a labelled simulation; mock cost is estimated, not billed.
- Fixed during the session: drill measured recovery late (now verified at rollback);
  promptfoo leakage test had guessed values (now taken from the data).

## 5. Course requirements found (instructor repo + course pages)
- **Locked stack:** OpenAI Agents SDK; Bedrock Claude Haiku 4.5 via LiteLLM
  `bedrock/converse/us.anthropic.claude-haiku-4-5-20251001-v1:0`; deploy on Lambda or
  AgentCore Runtime. ClaimSense matches.
- **AWS credentials:** the course provides them via the **AWS Lab Control Panel → Access
  Details** (accessId / accessKey), not by email. The lab account only works while its
  Start/Stop switch is on, and some lab logins have no Bedrock grants — then use your own AWS
  account.
- **M4 floor** (`labs/w17-prove/README.md`): gate green incl. adversarial ✅; live dashboard
  (latency / cost / eval-pass) — built from mock, needs a live run; RCA + runbook + handover ✅;
  **steering-committee deck — missing**.
- **Rule:** judgment artifacts (DECISIONS.md, charter, SoW, RCAs, runbook decisions) must be
  written by the learner; assistants draft questions, not text. `docs/DECISIONS.md` and the
  judgment parts of `docs/INCIDENT_REPORT.md` are currently drafted text → convert to question
  sheets.
- **Submission 1** (before the "Building Production Agents + Platform Engineering" class,
  Sunday): Week 1 + Week 2 deliverables + one screenshot proving the stack runs under your own
  account.

## 6. Open items
1. AWS account set up (in progress) → live run → screenshot for Submission 1.
2. Live golden run (`make eval-live`, ~$1) → fill `docs/OBSERVATION.md` §6; live dashboard.
3. promptfoo rubric run (needs Ollama or Bedrock).
4. Steering-committee deck (business-value numbers are the learner's).
5. Convert DECISIONS.md / RCA judgment sections into question sheets.
6. Deploy portal + API (`deploy/`), record demo, add URL to `docs/HANDOVER.md`.
7. Add the learner's own W1–W2 document links to `docs/HANDOVER.md`.
8. Tag the final codebase (e.g. `v1.0.0`) for Checkpoint 2.

## 7. AWS setup steps (for the live run)
1. Create the account (skip if you have one): aws.amazon.com → Create an AWS Account,
   Personal, Basic support (free).
2. Root user: enable MFA; use root only for billing.
3. Budgets → Monthly cost budget → **$10** alert.
4. IAM → Users → `claimsense-dev` (no console access) with this policy (`ClaimSenseBedrockInvoke`):
   ```json
   {"Version": "2012-10-17", "Statement": [{"Effect": "Allow",
     "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream",
                "bedrock:ListFoundationModels", "bedrock:GetFoundationModel"],
     "Resource": "*"}]}
   ```
   Add Lambda / S3 / CloudFront / CloudFormation / API Gateway / CloudWatch permissions later,
   only when deploying. Create an access key (CLI) and keep the CSV private — never in chat,
   email or Git.
5. Bedrock (us-east-1): the Model access page is retired; models enable on first use. Model
   catalog → Claude Haiku 4.5 → **Submit use case details** (personal learning project,
   synthetic data, internal users only) → test in the playground.
6. On your computer:
   ```
   aws configure                      # keys from the CSV, region us-east-1
   aws sts get-caller-identity
   git clone -b claude/claims-since-project-tlbgoc https://github.com/shrgen/CodeToSpeech.git
   cd CodeToSpeech/claimsense-capstone
   pip install -r requirements-live.txt
   python3 -m claimsense run --user alice --claim CLM-2024-1800 --brain bedrock
   ```
   Screenshot the output (`"verdict_source": "model"`) for Submission 1. If Bedrock returns an
   "on-demand throughput isn't supported" or access error, note the exact message.

## 8. Cost notes
- Live test runs: ~$0.005 per claim, ~$1 per full 150-case golden run (Haiku 4.5 at $1 / $5
  per million tokens — check Bedrock pricing for your region).
- Demo hosting: roughly $5–10 for a month (S3 + CloudFront, Lambda + API Gateway, CloudWatch).
  Tear down the stacks after grading.
- CI and every `make` target default to the mock brain: $0.

## 9. Everyday commands (from `claimsense-capstone/`)
```
make verify      # unit tests + smoke gate + regression cases
make golden      # 150-case release gate
make drill       # incident drill (writes runs/drill/)
make up          # portal + API on http://127.0.0.1:8080
make portal      # rebuild frontend/data.js from real pipeline runs
make eval-live   # golden gate on Bedrock (AWS credentials needed)
```
