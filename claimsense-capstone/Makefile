# ClaimSense — every target runs offline at $0 on the mock brain unless BRAIN=bedrock.
PY ?= python3
BRAIN ?= mock

.PHONY: help verify test smoke golden regression drill dashboard portal up docker eval-live clean

help:
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | sed 's/:.*## /\t/'

verify: test smoke regression ## unit tests + 10-case smoke gate + regression cases (what CI runs first)

test: ## unit tests
	$(PY) -m pytest -q tests

smoke: ## 10-case smoke gate
	$(PY) -m claimsense eval --suite smoke --min-pass 0.95 --brain $(BRAIN) --out runs/scratch/smoke.json

regression: ## cases spawned by incident drills
	@if [ -f evals/regression_set.json ]; then $(PY) -m claimsense eval --suite regression --min-pass 1.0 --brain $(BRAIN) --out runs/scratch/regression.json; fi

golden: ## full 150-case release gate (writes runs/eval_golden_<brain>_<release>.json + traces)
	$(PY) -m claimsense eval --suite golden --min-pass 0.95 --brain $(BRAIN)

drill: ## incident drill: inject v1.1.0 at #30, detect, roll back, verify, write RCA
	$(PY) ops/incident_drill.py --inject-at 30 --requests 100 --brain $(BRAIN)

dashboard: ## ops/dashboard.html from the latest golden traces
	$(PY) -m claimsense dashboard

portal: ## rebuild frontend/data.js from real pipeline runs
	$(PY) frontend/build_data.py

up: ## single-command start: portal + /recommend API on http://127.0.0.1:8080
	$(PY) -m claimsense serve --port 8080

docker: ## build and run the container (gate runs inside the build)
	docker build -t claimsense:local . && docker run --rm -p 8080:8080 claimsense:local

eval-live: ## golden gate on Bedrock (needs AWS creds + requirements-live.txt)
	$(MAKE) golden BRAIN=bedrock

clean:
	rm -rf runs/scratch .pytest_cache; find . -name __pycache__ -prune -exec rm -rf {} +
