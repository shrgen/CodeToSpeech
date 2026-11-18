# ClaimSense — single image: portal + /recommend API. The mock eval gate runs during the build,
# so a failing gate fails the build and no image is produced.
FROM python:3.12-slim
WORKDIR /app
ARG LIVE=0
COPY requirements-live.txt .
RUN if [ "$LIVE" = "1" ]; then pip install --no-cache-dir -r requirements-live.txt; fi
COPY claimsense ./claimsense
COPY releases ./releases
COPY evals ./evals
COPY frontend ./frontend
RUN python -m claimsense eval --suite golden --min-pass 0.95 --brain mock --out /tmp/gate.json \
 && python -m claimsense eval --suite smoke --min-pass 0.95 --brain mock --out /tmp/smoke.json \
 && rm -rf runs
ENV CLAIMSENSE_BRAIN=mock
EXPOSE 8080
USER nobody
CMD ["python", "-m", "claimsense", "serve", "--host", "0.0.0.0", "--port", "8080"]
