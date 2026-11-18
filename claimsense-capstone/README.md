# ClaimSense

First-decision co-pilot for AutoSure Insurance auto-claim adjusters (synthetic data;
Interview Kickstart FDE capstone). For one claim, ClaimSense reads the claims, policy and
document systems through a governed door, applies the policy manual with clause citations,
and posts a **recommendation** that a licensed human confirms. It never moves money.

```
make up         # portal + API on http://127.0.0.1:8080 (stdlib only, mock brain, $0)
make verify     # 49 unit tests + 10-case smoke gate + regression cases
make golden     # 150-case release gate: >= 95% AND zero adversarial failures
make drill      # incident drill: bad release -> detect -> rollback -> verified recovery -> RCA
```

| Result (mock brain, release v1.0.0) | Evidence |
|---|---|
| Golden gate 150/150, adversarial 30/30 | `runs/eval_golden_mock_v1.0.0.json` |
| Drill release v1.1.0 blocked: 118/150 | `runs/eval_golden_mock_v1.1.0.json` |
| promptfoo agreement 150/150 | `runs/promptfoo_golden_agreement.json` |
| Drill: detected in 14 requests, recovered 0.4 s, 0 unsafe approvals | `runs/drill/` |
| Live Bedrock run | not run yet — see `docs/OBSERVATION.md` §6 |

Live model: Claude Haiku 4.5 on Amazon Bedrock through the OpenAI Agents SDK
(`pip install -r requirements-live.txt`, AWS credentials, then `--brain bedrock`).

Docs: [architecture](docs/architecture.md) · [contracts](docs/contracts.md) ·
[runbook](docs/RUNBOOK.md) · [observation](docs/OBSERVATION.md) ·
[incident report](docs/INCIDENT_REPORT.md) · [handover](docs/HANDOVER.md) ·
[demo script](docs/DEMO_SCRIPT.md) · [decisions (draft)](docs/DECISIONS.md)
