"""Ops dashboard: one self-contained HTML file built from trace JSONL (+ eval reports).

Reads the same three numbers the CloudWatch dashboard reads — error rate, call volume,
p95 latency — plus eval pass rate and cost per resolution. When an eval report shares
trace ids with the traces, each request is also marked pass/fail, which gives the rolling
pass-rate line used by the incident drill.

No dependencies: charts are inline SVG generated here, with a small hover script.
"""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from .trace import is_error, load_spans, percentile, summarize

SLO_PASS = 0.95          # rolling eval pass rate must stay at or above this
SLO_ERROR = 0.05         # alarm: error rate above this over the window
WINDOW = 20              # rolling window, in requests


def request_rows(spans: list[dict[str, Any]], passed_by_trace: dict[str, bool] | None = None) -> list[dict]:
    rows = []
    for s in spans:
        if s["span"] != "claim.run":
            continue
        rows.append({
            "i": len(rows) + 1, "ts": s["start"], "trace_id": s["trace_id"], "claim_id": s.get("claim_id"),
            "release": s.get("release"), "outcome": s.get("outcome"),
            "error": is_error(s),
            "latency_ms": round(s["dur_ms"] + s.get("simulated_total_model_ms", 0), 1),
            "passed": (passed_by_trace or {}).get(s["trace_id"]),
        })
    return rows


def rolling(rows: list[dict], key, window: int = WINDOW) -> list[float | None]:
    out = []
    for k in range(len(rows)):
        w = [key(r) for r in rows[max(0, k - window + 1): k + 1]]
        w = [x for x in w if x is not None]
        out.append(sum(w) / len(w) if w else None)
    return out


def rolling_p95(rows: list[dict], window: int = WINDOW) -> list[float]:
    return [percentile([r["latency_ms"] for r in rows[max(0, k - window + 1): k + 1]], 95)
            for k in range(len(rows))]


def nice_max(v: float) -> float:
    """Round an axis maximum up to 1, 2, 2.5 or 5 x 10^k so the five ticks read cleanly."""
    import math
    if v <= 0:
        return 1.0
    e = 10 ** math.floor(math.log10(v))
    for m in (1, 2, 2.5, 5, 10):
        if v <= m * e + 1e-12:
            return m * e
    return 10 * e


# ── SVG line chart ─────────────────────────────────────────────────────────────
def line_chart(chart_id: str, ys: list[float | None], *, y_max: float, y_fmt: str, slo: float | None,
               slo_label: str, breach: str, events: list[dict] | None = None, height: int = 220) -> str:
    """breach: 'below' (bad when under the SLO) or 'above' (bad when over)."""
    w, h, l, r, t, b = 760, height, 70, 16, 22, 28
    y_max = nice_max(y_max)
    n = len(ys)
    if n == 0:
        return '<p class="muted">No requests in this trace file.</p>'
    x = lambda i: l + (w - l - r) * (i / max(n - 1, 1))
    y = lambda v: t + (h - t - b) * (1 - min(max(v, 0), y_max) / y_max)
    fmt = (lambda v: f"{v * 100:g}%") if y_fmt == "pct" else (lambda v: f"{v:,.0f} ms")
    parts = [f'<svg viewBox="0 0 {w} {h}" class="chart" role="img" aria-labelledby="{chart_id}-t" '
             f'data-chart="{chart_id}">']
    for k in range(5):                                         # recessive grid + y labels
        v = y_max * k / 4
        parts.append(f'<line x1="{l}" x2="{w - r}" y1="{y(v):.1f}" y2="{y(v):.1f}" class="grid"/>'
                     f'<text x="{l - 6}" y="{y(v) + 4:.1f}" class="tick" text-anchor="end">{fmt(v)}</text>')
    for k in sorted({1, n // 4, n // 2, 3 * n // 4, n} - {0}):
        parts.append(f'<text x="{x(k - 1):.1f}" y="{h - 8}" class="tick" text-anchor="middle">#{k}</text>')
    for k, ev in enumerate(events or []):                      # deployment events, labels staggered
        ex = x(ev["i"] - 1)
        parts.append(f'<line x1="{ex:.1f}" x2="{ex:.1f}" y1="{t}" y2="{h - b}" class="event"/>'
                     f'<text x="{ex + 4:.1f}" y="{t + 11 + 13 * (k % 3)}" class="evlabel">{html.escape(ev["label"])}</text>')
    if slo is not None:
        parts.append(f'<line x1="{l}" x2="{w - r}" y1="{y(slo):.1f}" y2="{y(slo):.1f}" class="slo"/>'
                     f'<text x="{w - r}" y="{y(slo) + (14 if y(slo) - t < 18 else -5):.1f}" class="slolabel" text-anchor="end">'
                     f'{html.escape(slo_label)}</text>')
    pts = [(x(i), y(v)) for i, v in enumerate(ys) if v is not None]
    if pts:
        d = "M" + " L".join(f"{px:.1f},{py:.1f}" for px, py in pts)
        parts.append(f'<path d="{d}" class="series"/>')
    if slo is not None:                                        # breach markers (status: critical)
        for i, v in enumerate(ys):
            if v is not None and ((breach == "below" and v < slo) or (breach == "above" and v > slo)):
                parts.append(f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="2.2" class="breach"/>')
    parts.append(f'<line class="xhair" y1="{t}" y2="{h - b}" x1="-10" x2="-10"/>'
                 f'<rect class="hit" x="{l}" y="{t}" width="{w - l - r}" height="{h - t - b}"/>')
    parts.append("</svg>")
    data = json.dumps({"l": l, "r": w - r, "n": n, "vals": [None if v is None else round(v, 4) for v in ys],
                       "fmt": y_fmt})
    return "".join(parts) + f'<script type="application/json" id="{chart_id}-data">{data}</script>'


CSS = """
:root{--surface:#fcfcfb;--page:#F9FAFB;--card:#fff;--line:#E5E7EB;--ink:#111827;--body:#374151;--muted:#6B7280;
--navy:#0F2D52;--series:#2a78d6;--grid:#ECEDEF;--good:#0ca30c;--critical:#d03b3b;--warn:#B45309}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--surface:#1a1a19;--page:#121211;--card:#1a1a19;
--line:#2e2e2c;--ink:#f0efec;--body:#d6d5ce;--muted:#c3c2b7;--navy:#9fb7d9;--series:#3987e5;--grid:#2a2a28;--warn:#e0a24a}}
:root[data-theme="dark"]{--surface:#1a1a19;--page:#121211;--card:#1a1a19;--line:#2e2e2c;--ink:#f0efec;--body:#d6d5ce;
--muted:#c3c2b7;--navy:#9fb7d9;--series:#3987e5;--grid:#2a2a28;--warn:#e0a24a}
*{box-sizing:border-box}body{margin:0;background:var(--page);color:var(--body);
font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif}
main{max-width:1100px;margin:0 auto;padding:20px 16px 48px}h1{color:var(--ink);font-size:21px;margin:0 0 4px}
h2{color:var(--navy);font-size:15px;margin:22px 0 8px}.muted{color:var(--muted)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin-top:14px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:11px 13px}
.kpi .n{font-size:23px;font-weight:600;color:var(--ink)}.kpi .l{font-size:12px;color:var(--muted)}
.kpi .s{font-size:11.5px;margin-top:3px;color:var(--muted)}.ok::before{content:"\\2714  ";color:var(--good)}
.bad::before{content:"\\2716  ";color:var(--critical)}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;position:relative}
.chart{width:100%;height:auto;display:block}.grid{stroke:var(--grid);stroke-width:1}
.tick{fill:var(--muted);font-size:11px}.series{fill:none;stroke:var(--series);stroke-width:2;stroke-linejoin:round}
.slo{stroke:var(--muted);stroke-width:1.2;stroke-dasharray:5 4}.slolabel{fill:var(--muted);font-size:11px}
.breach{fill:var(--critical);stroke:var(--surface);stroke-width:1}
.event{stroke:var(--warn);stroke-width:1.2;stroke-dasharray:2 3}.evlabel{fill:var(--warn);font-size:11px}
.xhair{stroke:var(--muted);stroke-width:1}.hit{fill:transparent;cursor:crosshair}
.tip{position:absolute;pointer-events:none;background:var(--ink);color:var(--page);font-size:12px;padding:4px 8px;
border-radius:6px;display:none;white-space:nowrap}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{text-align:left;padding:5px 8px;border-bottom:1px solid var(--line)}
th{color:var(--muted);font-weight:500}td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:12px}@media(max-width:760px){.cols{grid-template-columns:1fr}}
.note{font-size:12px;color:var(--muted);margin-top:6px}code{font-size:12px}
"""

JS = """
document.querySelectorAll('svg[data-chart]').forEach(svg=>{
 const id=svg.dataset.chart, d=JSON.parse(document.getElementById(id+'-data').textContent);
 const card=svg.closest('.card'), tip=card.querySelector('.tip'), xh=svg.querySelector('.xhair');
 const f=v=>v==null?'—':(d.fmt==='pct'?(v*100).toFixed(1)+'%':Math.round(v).toLocaleString()+' ms');
 svg.querySelector('.hit').addEventListener('mousemove',e=>{
  const p=svg.createSVGPoint();p.x=e.clientX;p.y=e.clientY;const q=p.matrixTransform(svg.getScreenCTM().inverse());
  const i=Math.max(0,Math.min(d.n-1,Math.round((q.x-d.l)/(d.r-d.l)*(d.n-1))));
  const x=d.l+(d.r-d.l)*(i/Math.max(d.n-1,1));xh.setAttribute('x1',x);xh.setAttribute('x2',x);
  tip.style.display='block';tip.textContent='request #'+(i+1)+' · '+f(d.vals[i]);
  const r=card.getBoundingClientRect();tip.style.left=Math.min(e.clientX-r.left+12,r.width-150)+'px';
  tip.style.top=(e.clientY-r.top-30)+'px';});
 svg.querySelector('.hit').addEventListener('mouseleave',()=>{tip.style.display='none';
  xh.setAttribute('x1',-10);xh.setAttribute('x2',-10);});
});
"""


def build(traces: Path, out: Path, eval_reports: list[Path] | None = None, events: list[dict] | None = None,
          title: str = "ClaimSense — operations dashboard", subtitle: str = "") -> dict[str, Any]:
    spans = load_spans(traces)
    passed: dict[str, bool] = {}
    latest_eval = None
    for p in eval_reports or []:
        rep = json.loads(Path(p).read_text(encoding="utf-8"))
        for r in rep.get("results", []):
            if r.get("trace_id"):
                passed[r["trace_id"]] = r["passed"]
        if rep.get("suite") == "golden" and rep.get("brain") == "mock" and rep.get("release") == "v1.0.0":
            latest_eval = rep
    rows = request_rows(spans, passed)
    s = summarize(spans)
    err = rolling(rows, lambda r: 1.0 if r["error"] else 0.0)
    pas = rolling(rows, lambda r: None if r["passed"] is None else (1.0 if r["passed"] else 0.0))
    p95 = rolling_p95(rows)
    have_pass = any(r["passed"] is not None for r in rows)
    graded = [r for r in rows if r["passed"] is not None]
    pass_rate = (sum(r["passed"] for r in graded) / len(graded)) if graded else None
    alarm = any(v is not None and v > SLO_ERROR for v in err[WINDOW - 1:]) if len(err) >= WINDOW else False

    def kpi(n, l, sub, cls=""):
        return f'<div class="kpi"><div class="n">{n}</div><div class="l">{l}</div><div class="s {cls}">{sub}</div></div>'

    eval_line = (f"{latest_eval['passed']}/{latest_eval['cases']} on golden v1.0.0 · gate "
                 f"{'passed' if latest_eval['gate_passed'] else 'FAILED'}") if latest_eval else "no golden report"
    k = [
        kpi(f"{s['call_volume']:,}", "Call volume", f"requests in <code>{html.escape(traces.name)}</code>"),
        kpi(f"{s['error_rate']:.1%}", "Error rate", f"SLO ≤ {SLO_ERROR:.0%} · alarm {'FIRED' if alarm else 'quiet'}",
            "bad" if alarm else "ok"),
        kpi(f"{s['p95_ms']:,.0f} ms", "p95 latency", f"p50 {s['p50_ms']:,.0f} ms"),
        kpi("—" if pass_rate is None else f"{pass_rate:.1%}", "Eval pass rate (this traffic)",
            f"SLO ≥ {SLO_PASS:.0%}", "" if pass_rate is None else ("ok" if pass_rate >= SLO_PASS else "bad")),
        kpi(f"${s['cost_per_resolution_usd']:.4f}", "Cost per resolution", "token-estimated (mock)"
            if any(r.get("brain") == "mock" for r in spans if r["span"] == "claim.run") else "from model usage"),
    ]
    charts = []
    if have_pass:
        charts.append(("pass", f"Rolling eval pass rate (last {WINDOW} requests)",
                       line_chart("pass", pas, y_max=1.0, y_fmt="pct", slo=SLO_PASS, slo_label="SLO 95%",
                                  breach="below", events=events)))
    charts.append(("err", f"Rolling error rate (last {WINDOW} requests) — the alarm metric",
                   line_chart("err", err, y_max=max(0.3, max([v for v in err if v is not None] or [0]) * 1.1),
                              y_fmt="pct", slo=SLO_ERROR, slo_label="alarm > 5%", breach="above", events=events)))
    charts.append(("lat", f"Rolling p95 latency (last {WINDOW} requests)",
                   line_chart("lat", p95, y_max=max(p95 or [1]) * 1.15, y_fmt="ms", slo=None, slo_label="",
                              breach="above", events=events)))

    def table(d: dict[str, int], head: str) -> str:
        body = "".join(f"<tr><td>{html.escape('refused by the door (403)' if k == 'None' else k)}</td>"
                       f"<td class='num'>{v}</td></tr>" for k, v in sorted(d.items()))
        return f"<table><tr><th>{head}</th><th class='num'>requests</th></tr>{body}</table>"

    sim_note = ("Latency includes a <b>labelled simulation</b> of hosted-model time (lognormal, median ~700 ms "
                "per model call) because the mock brain answers in microseconds. Live Bedrock runs record real "
                "latency instead.") if s["latency_includes_simulated_model_time"] else "Latency is measured wall time."
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>ClaimSense Ops</title><style>{CSS}</style></head>
<body><main><h1>{html.escape(title)}</h1>
<div class="muted">{html.escape(subtitle) or "Built from traces by <code>python3 -m claimsense dashboard</code>"}</div>
<div class="kpis">{''.join(k)}</div>
{''.join(f'<h2 id="{cid}-t">{html.escape(t)}</h2><div class="card">{svg}<div class="tip"></div></div>' for cid, t, svg in charts)}
<p class="note">{sim_note} Error = the request raised, or its verdict came from the deterministic fallback
(the model's output was rejected). Golden eval: {html.escape(eval_line)}.</p>
<div class="cols"><div><h2>Outcomes</h2><div class="card">{table(s['outcomes'], 'outcome')}</div></div>
<div><h2>Verdict source</h2><div class="card">{table(s['verdict_sources'], 'source')}</div></div></div>
</main><script>{JS}</script></body></html>"""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    return {"summary": s, "alarm_fired": alarm, "pass_rate": pass_rate, "rows": len(rows)}
