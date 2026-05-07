"""
Generates a self-contained HTML cost report — no external CSS/JS dependencies.
Inline SVG bar chart + sortable table via vanilla JS.
"""

from __future__ import annotations

import html
from datetime import datetime, timezone

from waste_calculator import PodCost


def _fmt_cost(v: float | None) -> str:
    if v is None:
        return "—"
    return f"${v:.4f}"


def _fmt_pct(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:.1f}%"


def _fmt_cpu(m: int | None) -> str:
    if m is None:
        return "—"
    return f"{m}m" if m < 1000 else f"{m/1000:.1f}"


def _fmt_mem(mi: int | None) -> str:
    if mi is None:
        return "—"
    if mi >= 1024:
        return f"{mi/1024:.1f}Gi"
    return f"{mi}Mi"


def _flag_badge(flags: list[str]) -> str:
    if not flags:
        return ""
    badges = "".join(
        f'<span class="flag">{html.escape(f)}</span>' for f in flags
    )
    return badges


def _bar_chart(rows: list[PodCost], top: int = 10) -> str:
    # Top N pods by waste cost (or pod cost if no metrics)
    chart_rows = sorted(
        rows,
        key=lambda r: -(r.waste_cost_hr or r.pod_cost_hr),
    )[:top]

    if not chart_rows:
        return ""

    max_val = max((r.waste_cost_hr or r.pod_cost_hr) for r in chart_rows) or 1
    bar_h = 28
    gap = 6
    label_w = 220
    bar_max_w = 380
    chart_h = (bar_h + gap) * len(chart_rows) + 20
    svg_w = label_w + bar_max_w + 100

    bars = []
    for i, r in enumerate(chart_rows):
        val = r.waste_cost_hr or r.pod_cost_hr
        bar_w = int(val / max_val * bar_max_w)
        y = i * (bar_h + gap) + 10
        label = html.escape(f"{r.namespace}/{r.pod}"[:34])
        cost_label = f"${val:.4f}/hr"
        color = "#f85149" if (r.waste_cost_hr or 0) > 0 else "#388bfd"
        bars.append(
            f'<text x="{label_w - 6}" y="{y + bar_h//2 + 5}" '
            f'text-anchor="end" fill="#8b949e" font-size="11">{label}</text>'
            f'<rect x="{label_w}" y="{y}" width="{bar_w}" height="{bar_h}" '
            f'rx="3" fill="{color}" opacity="0.85"/>'
            f'<text x="{label_w + bar_w + 6}" y="{y + bar_h//2 + 5}" '
            f'fill="#c9d1d9" font-size="11">{cost_label}</text>'
        )

    return f"""
<div class="chart-section">
  <h2>Top {len(chart_rows)} Pods by Wasted Cost</h2>
  <svg width="{svg_w}" height="{chart_h}" style="max-width:100%">
    {''.join(bars)}
  </svg>
  <p class="chart-note">Red = measured waste &nbsp;|&nbsp; Blue = pod cost share (no metrics)</p>
</div>"""


def _table_rows(rows: list[PodCost]) -> str:
    html_rows = []
    for r in rows:
        waste_cls = ""
        if r.waste_pct is not None:
            if r.waste_pct >= 70:
                waste_cls = "crit"
            elif r.waste_pct >= 40:
                waste_cls = "warn"

        html_rows.append(f"""
      <tr>
        <td>{html.escape(r.namespace)}</td>
        <td class="mono">{html.escape(r.pod)}</td>
        <td>{html.escape(r.instance_type)}</td>
        <td class="num">{_fmt_cost(r.node_cost_hr)}</td>
        <td class="num">{_fmt_cost(r.pod_cost_hr)}</td>
        <td class="num">{_fmt_cpu(r.req_cpu_m)}</td>
        <td class="num">{_fmt_cpu(r.actual_cpu_m)}</td>
        <td class="num">{_fmt_mem(r.req_mem_mi)}</td>
        <td class="num {waste_cls}">{_fmt_cost(r.waste_cost_hr)}</td>
        <td class="num {waste_cls}">{_fmt_pct(r.waste_pct)}</td>
        <td>{_flag_badge(r.flags)}</td>
      </tr>""")
    return "".join(html_rows)


def generate_html(rows: list[PodCost], summary: dict) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    has_metrics = summary["pods_with_metrics"] > 0

    waste_indicator = (
        f'<span class="crit">${summary["total_waste_hr"]:.4f}/hr wasted '
        f'({summary["waste_pct"]}%)</span>'
        if has_metrics
        else '<span class="warn">No metrics-server — estimates only</span>'
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>K8s Cost Report — {ts}</title>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
          background:#0d1117;color:#c9d1d9;padding:24px}}
    h1{{font-size:1.3rem;color:#e6edf3;margin-bottom:4px}}
    .meta{{font-size:.8rem;color:#8b949e;margin-bottom:20px}}
    .summary{{display:flex;gap:16px;flex-wrap:wrap;margin-bottom:28px}}
    .card{{background:#161b22;border:1px solid #30363d;border-radius:8px;
           padding:14px 20px;min-width:140px}}
    .card .label{{font-size:.72rem;color:#8b949e;text-transform:uppercase;letter-spacing:.05em}}
    .card .value{{font-size:1.4rem;font-weight:700;margin-top:4px;color:#e6edf3}}
    .chart-section{{margin-bottom:28px}}
    .chart-section h2{{font-size:1rem;color:#e6edf3;margin-bottom:12px}}
    .chart-note{{font-size:.75rem;color:#8b949e;margin-top:8px}}
    table{{width:100%;border-collapse:collapse;font-size:.82rem}}
    th{{background:#161b22;color:#8b949e;font-weight:600;padding:8px 10px;
        text-align:left;border-bottom:2px solid #30363d;cursor:pointer;user-select:none;
        white-space:nowrap}}
    th:hover{{color:#e6edf3}}
    th::after{{content:" ↕";font-size:.7rem;opacity:.5}}
    td{{padding:7px 10px;border-bottom:1px solid #21262d;vertical-align:middle}}
    tr:hover td{{background:#161b22}}
    .mono{{font-family:monospace;font-size:.8rem}}
    .num{{text-align:right;font-variant-numeric:tabular-nums}}
    .crit{{color:#f85149;font-weight:600}}
    .warn{{color:#d29922}}
    .flag{{display:inline-block;padding:1px 6px;border-radius:10px;
           font-size:.7rem;background:#2d2200;color:#d29922;margin-right:4px}}
    h2{{font-size:1rem;color:#e6edf3;margin-bottom:16px}}
    .table-wrap{{background:#0d1117;border:1px solid #30363d;border-radius:8px;overflow:auto}}
  </style>
</head>
<body>
  <h1>🩺 Kubernetes Cost Report</h1>
  <p class="meta">Generated {ts} &nbsp;|&nbsp; {summary['total_pods']} pods analysed
     &nbsp;|&nbsp; {waste_indicator}</p>

  <div class="summary">
    <div class="card">
      <div class="label">Total Cost</div>
      <div class="value">${summary['total_cost_hr']:.3f}<small style="font-size:.9rem">/hr</small></div>
    </div>
    <div class="card">
      <div class="label">Wasted Cost</div>
      <div class="value {'crit' if has_metrics else ''}">${summary['total_waste_hr']:.3f}<small style="font-size:.9rem">/hr</small></div>
    </div>
    <div class="card">
      <div class="label">Waste %</div>
      <div class="value {'crit' if summary['waste_pct'] > 40 else 'warn'}">{summary['waste_pct']}%</div>
    </div>
    <div class="card">
      <div class="label">Flagged Pods</div>
      <div class="value warn">{summary['flagged_pods']}</div>
    </div>
  </div>

  {_bar_chart(rows)}

  <h2>Pod Cost Breakdown</h2>
  <div class="table-wrap">
    <table id="t">
      <thead>
        <tr>
          <th>Namespace</th><th>Pod</th><th>Instance</th>
          <th>Node $/hr</th><th>Pod $/hr</th>
          <th>CPU Req</th><th>CPU Use</th><th>Mem Req</th>
          <th>Waste $/hr</th><th>Waste %</th><th>Flags</th>
        </tr>
      </thead>
      <tbody>
        {_table_rows(rows)}
      </tbody>
    </table>
  </div>

  <script>
    const t = document.getElementById('t');
    let asc = {{}};
    t.querySelectorAll('th').forEach((th, i) => {{
      th.addEventListener('click', () => {{
        const tbody = t.querySelector('tbody');
        const rows = [...tbody.rows];
        asc[i] = !asc[i];
        rows.sort((a, b) => {{
          const av = a.cells[i].innerText.trim();
          const bv = b.cells[i].innerText.trim();
          const an = parseFloat(av.replace(/[^0-9.-]/g,''));
          const bn = parseFloat(bv.replace(/[^0-9.-]/g,''));
          const cmp = isNaN(an) || isNaN(bn) ? av.localeCompare(bv) : an - bn;
          return asc[i] ? cmp : -cmp;
        }});
        rows.forEach(r => tbody.appendChild(r));
      }});
    }});
  </script>
</body>
</html>"""


def write_report(rows: list[PodCost], summary: dict, path: str):
    content = generate_html(rows, summary)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
