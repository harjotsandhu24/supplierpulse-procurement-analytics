"""Static, self-contained HTML dashboard (three views) built with Plotly.

The file embeds plotly.js and all data, so it opens offline in any modern browser with no
installation. Views can be opened directly with #overview, #performance or #decisions.
"""

from __future__ import annotations

import html
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.offline import get_plotlyjs

NAVY = "#1F2A44"
SLATE = "#64748B"
SLATE_LIGHT = "#CBD5E1"
TEAL = "#0F766E"
INK = "#0F172A"
MUTED = "#475569"
GRID = "#E2E8F0"
CRIT = "#B42318"
WARN = "#B54708"
GOOD = "#067647"
FONT = "Segoe UI, -apple-system, Helvetica Neue, Arial, sans-serif"


def money(x: float) -> str:
    if pd.isna(x):
        return "-"
    sign = "-" if x < 0 else ""
    ax = abs(x)
    if ax >= 1e9:
        return f"{sign}${ax / 1e9:,.2f}B"
    if ax >= 1e6:
        return f"{sign}${ax / 1e6:,.1f}M"
    if ax >= 1e3:
        return f"{sign}${ax / 1e3:,.0f}K"
    return f"{sign}${ax:,.0f}"


def pct(x: float, d: int = 1) -> str:
    return "-" if pd.isna(x) else f"{x * 100:.{d}f}%"


def esc(s) -> str:
    return html.escape(str(s))


def _layout(fig: go.Figure, height: int, left: int = 10, bottom: int = 40, **kw) -> go.Figure:
    fig.update_layout(
        height=height, margin=dict(l=left, r=24, t=12, b=bottom), paper_bgcolor="white", plot_bgcolor="white",
        font=dict(family=FONT, size=13, color=INK), showlegend=False,
        hoverlabel=dict(bgcolor="white", bordercolor=GRID, font=dict(family=FONT, size=12, color=INK)), **kw,
    )
    fig.update_xaxes(gridcolor=GRID, zeroline=False, linecolor=GRID, tickfont=dict(color=MUTED))
    fig.update_yaxes(gridcolor=GRID, zeroline=False, linecolor=GRID, tickfont=dict(color=MUTED))
    return fig


# ---------------------------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------------------------

def chart_family(r) -> go.Figure:
    f = r.families.sort_values("spend")
    fig = go.Figure(go.Bar(
        x=f["spend"] / 1e6, y=f["spend_family"], orientation="h", marker=dict(color=NAVY, cornerradius=3),
        text=[f"{money(v)}  ({s:.0%})" for v, s in zip(f["spend"], f["share"])], textposition="outside",
        textfont=dict(color=INK, size=12), cliponaxis=False,
        customdata=f[["vendor_count", "po_count"]].values,
        hovertemplate="<b>%{y}</b><br>Spend: $%{x:,.1f}M<br>Vendors: %{customdata[0]:,}<br>POs: %{customdata[1]:,}<extra></extra>",
    ))
    fig = _layout(fig, 430, left=10, bottom=30)
    fig.update_xaxes(title=dict(text="Committed spend, $M", font=dict(color=MUTED, size=12)), range=[0, f["spend"].max() / 1e6 * 1.32])
    fig.update_yaxes(gridcolor="white", tickfont=dict(color=INK, size=12))
    return fig


def chart_fy(r) -> go.Figure:
    f = r.fy_spend
    colors = [NAVY if x else SLATE_LIGHT for x in f["in_focus_window"]]
    fig = go.Figure(go.Bar(
        x=[f"FY{str(y)[2:]}" for y in f["fiscal_year"]], y=f["spend"] / 1e6, marker=dict(color=colors, cornerradius=3),
        customdata=f[["po_count", "active_vendors"]].values,
        hovertemplate="<b>%{x}</b><br>Spend: $%{y:,.1f}M<br>POs: %{customdata[0]:,}<br>Vendors: %{customdata[1]:,}<extra></extra>",
    ))
    fig = _layout(fig, 300, left=10, bottom=30)
    fig.update_yaxes(title=dict(text="$M", font=dict(color=MUTED, size=12)))
    fig.update_xaxes(gridcolor="white", tickfont=dict(size=11))
    return fig


def chart_category_dependency(r) -> go.Figure:
    c = r.settings.concentration
    cat = r.categories[r.categories["spend"] >= c["min_category_spend"]].head(15).iloc[::-1]
    colors = [CRIT if s >= c["single_vendor_share"] else (WARN if h >= c["hhi_highly_concentrated"] else SLATE)
              for s, h in zip(cat["top_vendor_share"], cat["hhi"])]
    labels = [lab if len(lab) <= 44 else lab[:43].rstrip() + "…" for lab in cat["class_label"]]
    fig = go.Figure(go.Bar(
        x=cat["top_vendor_share"] * 100, y=labels, orientation="h", marker=dict(color=colors, cornerradius=3),
        text=[f"{s:.0%} · {money(v)}" for s, v in zip(cat["top_vendor_share"], cat["spend"])], textposition="outside",
        textfont=dict(size=11, color=INK), cliponaxis=False,
        customdata=list(zip(cat["top_vendor_name"], cat["vendor_count"], cat["hhi"].round(0), cat["spend"] / 1e6)),
        hovertemplate=("<b>%{y}</b><br>Top vendor: %{customdata[0]}<br>Top-vendor share: %{x:.0f}%<br>"
                       "Vendors in class: %{customdata[1]}<br>HHI: %{customdata[2]:,.0f}<br>Spend: $%{customdata[3]:,.1f}M<extra></extra>"),
    ))
    fig = _layout(fig, 470, left=10, bottom=40)
    fig.update_xaxes(range=[0, 128], title=dict(text="Share of class spend held by the largest vendor (%)", font=dict(color=MUTED, size=12)),
                     tickvals=[0, 25, 50, 75, 90, 100])
    fig.add_vline(x=90, line=dict(color=CRIT, width=1, dash="dot"))
    fig.update_yaxes(gridcolor="white", tickfont=dict(size=11.5, color=INK))
    return fig


def chart_pareto(r) -> go.Figure:
    v = r.vendors.head(300)
    fig = go.Figure(go.Scatter(
        x=v["rank"], y=v["cumulative_share"] * 100, mode="lines", line=dict(color=NAVY, width=2),
        customdata=v[["vendor_name"]].values,
        hovertemplate="Top %{x} vendors<br>Cumulative share: %{y:.1f}%<br>#%{x}: %{customdata[0]}<extra></extra>",
    ))
    k = r.kpis["vendors_for_80pct"]
    fig.add_hline(y=80, line=dict(color=SLATE, width=1, dash="dot"))
    fig.add_annotation(x=k, y=80, text=f"{k} vendors = 80% of spend", showarrow=True, arrowhead=0, ax=60, ay=40,
                       font=dict(size=12, color=INK), arrowcolor=SLATE)
    fig = _layout(fig, 300, left=10, bottom=40)
    fig.update_yaxes(range=[0, 101], title=dict(text="Cumulative share of spend (%)", font=dict(color=MUTED, size=12)))
    fig.update_xaxes(title=dict(text=f"Vendors ranked by spend (top 300 of {r.kpis['active_vendors']:,})", font=dict(color=MUTED, size=12)))
    return fig


def chart_monthly_otif(r) -> go.Figure:
    m = r.monthly_otif
    target = r.settings.scorecard["otif_target"]
    fig = go.Figure(go.Scatter(
        x=m["month"], y=m["otif_rate"] * 100, mode="lines+markers", line=dict(color=TEAL, width=2),
        marker=dict(size=8, color=TEAL, line=dict(color="white", width=2)),
        customdata=m[["due_lines", "otif_lines"]].values,
        hovertemplate="<b>%{x|%b %Y}</b><br>OTIF: %{y:.1f}%<br>%{customdata[1]:,} of %{customdata[0]:,} due lines<extra></extra>",
    ))
    fig.add_hline(y=target * 100, line=dict(color=SLATE, width=1, dash="dot"))
    fig.add_annotation(x=m["month"].iloc[1], y=target * 100, text=f"Target {target:.0%}", showarrow=False, yshift=10,
                       font=dict(size=11, color=MUTED))
    fig = _layout(fig, 300, left=10, bottom=30)
    fig.update_yaxes(range=[70, 100], title=dict(text="OTIF (%)", font=dict(color=MUTED, size=12)))
    fig.update_xaxes(tickformat="%b %y", dtick="M3")
    return fig


def chart_perf_dependency(r) -> go.Figure:
    sc = r.scorecard[r.scorecard["evidence_status"] != "Insufficient evidence"]
    acc = r.settings.scorecard["tier_acceptable"]
    dep = r.settings.exceptions["high_dependency_category_share"]
    color = [CRIT if q == "Critical - act now" else (WARN if q == "Develop or replace" else NAVY) for q in sc["action_quadrant"]]
    symbol = ["circle-open" if s == "Provisional" else "circle" for s in sc["evidence_status"]]
    # Simple label placement: cycle positions for points close to an already-labelled point
    positions, placed = [], []
    for x, y in zip(sc["max_category_share"] * 100, sc["performance_score"]):
        near = sum(1 for px, py in placed if abs(px - x) < 9 and abs(py - y) < 6)
        positions.append(["top center", "bottom center", "middle right", "middle left"][near % 4])
        placed.append((x, y))
    fig = go.Figure(go.Scatter(
        x=sc["max_category_share"] * 100, y=sc["performance_score"], mode="markers+text", text=sc["supplier_id"],
        textposition=positions, textfont=dict(size=11, color=INK),
        marker=dict(size=12, color=color, symbol=symbol, line=dict(color="white", width=2)),
        customdata=list(zip(sc["action_quadrant"], sc["otif_rate"] * 100, sc["evidence_status"])),
        hovertemplate=("<b>%{text}</b><br>Score: %{y:.1f}<br>Largest category share: %{x:.0f}%<br>OTIF: %{customdata[1]:.1f}%<br>"
                       "%{customdata[2]}<br>%{customdata[0]}<extra></extra>"),
    ))
    fig.add_hline(y=acc, line=dict(color=SLATE, width=1, dash="dot"))
    fig.add_vline(x=dep * 100, line=dict(color=SLATE, width=1, dash="dot"))
    for x, y, t in [(3, 104, "Maintain"), (dep * 100 + 2, 104, "Strategic: protect"), (3, 14, "Develop or replace"),
                    (dep * 100 + 2, 14, "Critical: act now")]:
        fig.add_annotation(x=x, y=y, text=t, showarrow=False, xanchor="left", font=dict(size=11, color=MUTED))
    fig = _layout(fig, 360, left=10, bottom=40)
    fig.update_xaxes(range=[0, 105], title=dict(text="Dependency: supplier's share of its main category (%)", font=dict(color=MUTED, size=12)))
    fig.update_yaxes(range=[10, 108], title=dict(text="Performance score", font=dict(color=MUTED, size=12)))
    return fig


def chart_realloc(r) -> go.Figure:
    rr = r.realloc
    fig = go.Figure(go.Bar(
        x=[f"{s:.0%}" for s in rr["share_moved"]], y=rr["late_lines_avoided"], marker=dict(color=TEAL, cornerradius=3),
        text=[f"{v:.0f}" for v in rr["late_lines_avoided"]], textposition="outside", cliponaxis=False, textfont=dict(color=INK),
        customdata=list(zip(rr["late_cost_avoided"], rr["price_impact"], rr["from_share_after"] * 100)),
        hovertemplate=("Move %{x} of volume<br>Late lines avoided/yr: %{y:.1f}<br>Handling cost avoided: $%{customdata[0]:,.0f}<br>"
                       "Price impact: $%{customdata[1]:,.0f}<br>Incumbent category share after: %{customdata[2]:.0f}%<extra></extra>"),
    ))
    fig = _layout(fig, 260, left=10, bottom=40)
    fig.update_yaxes(title=dict(text="Late lines avoided per year", font=dict(color=MUTED, size=12)),
                     range=[0, rr["late_lines_avoided"].max() * 1.25 + 1])
    fig.update_xaxes(title=dict(text="Share of the incumbent's volume moved", font=dict(color=MUTED, size=12)), gridcolor="white")
    return fig


# ---------------------------------------------------------------------------------------------
# HTML pieces
# ---------------------------------------------------------------------------------------------

def tile(label: str, value: str, note: str = "") -> str:
    return (f'<div class="tile"><div class="tile-label">{esc(label)}</div><div class="tile-value">{esc(value)}</div>'
            f'<div class="tile-note">{esc(note)}</div></div>')


def card(title: str, body: str, sub: str = "", cls: str = "") -> str:
    s = f'<div class="card-sub">{esc(sub)}</div>' if sub else ""
    return f'<section class="card {cls}"><h3>{esc(title)}</h3>{s}{body}</section>'


def chart_div(div_id: str) -> str:
    return f'<div class="chart" id="{div_id}"></div>'


def status_dot(level: str) -> str:
    cls = {"High": "crit", "Critical - act now": "crit", "At risk": "crit", "Medium": "warn",
           "Improvement needed": "warn", "Develop or replace": "warn", "Low": "ok", "Preferred": "ok"}.get(level, "neutral")
    return f'<span class="dot {cls}"></span>'


def pretty(text: str) -> str:
    """Escape and swap ASCII operators for typographic ones in displayed evidence text."""
    return esc(text).replace("&gt;= ", "≥ ").replace(" -&gt; ", " → ")


def scorecard_table(r) -> str:
    sc = r.scorecard
    rows = []
    for x in sc.itertuples():
        score = "" if pd.isna(x.performance_score) else f"{x.performance_score:.1f}"
        width = 0 if pd.isna(x.performance_score) else x.performance_score
        rank = "" if pd.isna(x.rank) else str(int(x.rank))
        bar = f'<div class="bar"><span style="width:{width:.0f}%"></span></div>' if score else ""
        evidence = {"Ranked": "", "Provisional": "Provisional", "Insufficient evidence": "Insufficient evidence"}[x.evidence_status]
        lt = "" if pd.isna(x.lead_time_sd) else f"{x.lead_time_sd:.1f}"
        rows.append(
            f"<tr><td class='num'>{rank}</td><td><b>{esc(x.supplier_id)}</b></td><td>{esc(x.main_category_id)}</td>"
            f"<td class='num'>{x.due_lines:,}</td><td class='num'>{pct(x.otif_rate)}</td><td class='num'>{pct(x.reject_rate, 2)}</td>"
            f"<td class='num'>{lt}</td><td class='num'>{x.avg_days_late_all_due:.1f}</td>"
            f"<td class='scorecell'><span class='num'>{score}</span>{bar}</td>"
            f"<td>{status_dot(x.performance_tier)}{esc(x.performance_tier)}<div class='small'>{esc(evidence)}</div></td>"
            f"<td>{esc(x.dependency_risk)}</td><td>{status_dot(x.action_quadrant)}{esc(x.action_quadrant)}</td></tr>"
        )
    head = ("<tr><th>Rank</th><th>Supplier</th><th>Category</th><th>Due lines</th><th>OTIF</th><th>Reject rate</th>"
            "<th>Lead-time SD (d)</th><th>Avg days late</th><th>Score (0-100)</th><th>Tier</th><th>Dependency</th><th>Action quadrant</th></tr>")
    return f"<table class='tbl'><thead>{head}</thead><tbody>{''.join(rows)}</tbody></table>"


def action_table(r, limit: int = 12) -> str:
    a = r.actions.head(limit)
    rows = []
    for x in a.itertuples():
        origin = "Observed" if x.data_origin.startswith("Observed") else "Synthetic"
        rows.append(
            f"<tr><td class='nowrap'>{status_dot(x.priority)}<b>{esc(x.priority)}</b></td>"
            f"<td><span class='origin {origin.lower()}'>{origin}</span></td>"
            f"<td><b>{esc(x.supplier_or_category)}</b><div class='small'>{esc(x.issue)}</div></td>"
            f"<td>{pretty(x.supporting_metric)}</td><td>{esc(x.recommended_action)}</td></tr>"
        )
    head = "<tr><th>Priority</th><th>Data</th><th>Supplier or category / issue</th><th>Evidence</th><th>Recommended action</th></tr>"
    return f"<table class='tbl actions'><thead>{head}</thead><tbody>{''.join(rows)}</tbody></table>"


def exception_summary(r) -> str:
    reg = r.register
    d = r.definitions.set_index("rule")
    counts = reg.groupby("rule")["exception_id"].size()
    rows = []
    for rule, n in counts.items():
        origin = "Observed" if d.loc[rule, "data_origin"].startswith("Observed") else "Synthetic"
        rows.append(f"<tr><td><b>{rule}</b></td><td>{esc(d.loc[rule, 'exception_type'])}</td>"
                    f"<td><span class='origin {origin.lower()}'>{origin}</span></td><td class='num'>{int(n)}</td></tr>")
    head = "<tr><th>Rule</th><th>Exception</th><th>Data</th><th>Count</th></tr>"
    return f"<table class='tbl compact'><thead>{head}</thead><tbody>{''.join(rows)}</tbody></table>"


def overdue_table(r) -> str:
    od = r.facts[r.facts["overdue"]].sort_values(["days_late", "po_line_id"], ascending=[False, True])
    rows = "".join(
        f"<tr><td>{esc(x.po_line_id)}</td><td>{esc(x.supplier_id)}</td><td>{x.promised_date:%d %b %Y}</td>"
        f"<td class='num'>{x.open_qty:,} of {x.ordered_qty:,}</td><td class='num'>{x.days_late:.0f}</td><td class='num'>${x.open_value:,.0f}</td></tr>"
        for x in od.itertuples())
    head = "<tr><th>PO line</th><th>Supplier</th><th>Promised</th><th>Open units</th><th>Days late</th><th>Open value</th></tr>"
    return f"<table class='tbl compact'><thead>{head}</thead><tbody>{rows}</tbody></table>"


CSS = """
:root{--navy:#1F2A44;--slate:#475569;--muted:#64748B;--teal:#0F766E;--ink:#0F172A;--line:#E2E8F0;--bg:#F6F8FA;--crit:#B42318;--warn:#B54708;--ok:#067647}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:"Segoe UI",-apple-system,"Helvetica Neue",Arial,sans-serif;font-size:14px;line-height:1.45}
header{background:var(--navy);color:#fff;padding:18px 32px 0}
.brand{display:flex;justify-content:space-between;align-items:flex-end;flex-wrap:wrap;gap:8px}
.brand h1{margin:0;font-size:22px;font-weight:600;letter-spacing:.2px}
.brand .subtitle{color:#CBD5E1;font-size:13px;margin-top:2px}
.brand .meta{color:#CBD5E1;font-size:12px;text-align:right}
nav{display:flex;gap:4px;margin-top:16px;flex-wrap:wrap}
nav button{background:transparent;border:0;color:#CBD5E1;font:inherit;font-size:14px;padding:10px 18px;border-bottom:3px solid transparent;cursor:pointer}
nav button.active{color:#fff;border-bottom-color:#5EEAD4;font-weight:600}
main{max-width:1400px;margin:0 auto;padding:22px 32px 40px}
.view{display:none}.view.active{display:block}
.question{display:flex;justify-content:space-between;align-items:baseline;gap:16px;margin:0 0 14px;flex-wrap:wrap}
.question h2{margin:0;font-size:19px;font-weight:600;color:var(--navy)}
.datanote{font-size:12.5px;color:var(--slate);border:1px solid var(--line);background:#fff;border-radius:6px;padding:6px 10px}
.datanote b{color:var(--ink)}
.synthetic-banner{border-left:4px solid var(--slate);background:#fff;padding:10px 14px;margin-bottom:16px;font-size:13px;color:var(--slate);border-radius:4px}
.synthetic-banner b{color:var(--ink)}
.tiles{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:16px}
.tile{background:#fff;border:1px solid var(--line);border-radius:8px;padding:14px 16px}
.tile-label{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.4px}
.tile-value{font-size:26px;font-weight:600;color:var(--navy);margin-top:4px}
.tile-note{font-size:12px;color:var(--muted);margin-top:2px;min-height:16px}
.grid{display:grid;gap:16px;margin-bottom:16px}
.g2{grid-template-columns:1fr 1fr}.g32{grid-template-columns:3fr 2fr}.g23{grid-template-columns:2fr 3fr}
.card{background:#fff;border:1px solid var(--line);border-radius:8px;padding:16px 18px;overflow-x:auto}
.card h3{margin:0;font-size:15px;font-weight:600;color:var(--navy)}
.card-sub{font-size:12.5px;color:var(--muted);margin:2px 0 8px}
.chart{width:100%}
.legend{font-size:12px;color:var(--slate);margin-top:6px}
.legend span{display:inline-block;margin-right:14px}
.sw{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:-1px}
ul.findings{margin:6px 0 0;padding-left:18px}
ul.findings li{margin:6px 0}
.tbl{width:100%;border-collapse:collapse;font-size:13px}
.tbl th{text-align:left;font-weight:600;color:var(--slate);border-bottom:2px solid var(--line);padding:7px 8px;font-size:12px;vertical-align:bottom}
.tbl td{border-bottom:1px solid var(--line);padding:7px 8px;vertical-align:top}
.tbl td.num,.tbl .num{text-align:right;font-variant-numeric:tabular-nums}
.tbl.compact td{padding:5px 8px}
.tbl.actions td{font-size:12.5px}
.small{font-size:11.5px;color:var(--muted)}
.nowrap{white-space:nowrap}
.scorecell{min-width:120px}
.scorecell .num{display:inline-block;width:36px;font-weight:600}
.bar{display:inline-block;width:70px;height:8px;background:#EEF2F6;border-radius:4px;vertical-align:middle;margin-left:6px}
.bar span{display:block;height:8px;background:var(--teal);border-radius:4px}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;vertical-align:1px;background:#94A3B8}
.dot.crit{background:var(--crit)}.dot.warn{background:var(--warn)}.dot.ok{background:var(--ok)}
.origin{font-size:11px;border:1px solid var(--line);border-radius:4px;padding:1px 6px;color:var(--slate);white-space:nowrap}
.origin.observed{border-color:#9FB4CC;color:var(--navy)}
footer{max-width:1400px;margin:0 auto;padding:0 32px 30px;color:var(--muted);font-size:12px}
@media (max-width:900px){.tiles{grid-template-columns:1fr 1fr}.g2,.g32,.g23{grid-template-columns:1fr}main,header,footer{padding-left:16px;padding-right:16px}}
"""

JS = """
const FIGS = __FIGS__;
const VIEWS = {overview:['fig_family','fig_fy','fig_dep','fig_pareto'], performance:['fig_otif','fig_quad'], decisions:['fig_realloc']};
const drawn = {};
function draw(view){
  for (const id of VIEWS[view]) {
    const el = document.getElementById(id);
    if (!drawn[id]) { const f = FIGS[id]; Plotly.newPlot(el, f.data, f.layout, {displayModeBar:false, responsive:true}); drawn[id]=true; }
    else { Plotly.Plots.resize(el); }
  }
}
function show(view){
  if (!VIEWS[view]) view = 'overview';
  document.querySelectorAll('.view').forEach(v => v.classList.toggle('active', v.id === view));
  document.querySelectorAll('nav button').forEach(b => b.classList.toggle('active', b.dataset.view === view));
  draw(view);
  document.body.dataset.ready = view;
}
document.querySelectorAll('nav button').forEach(b => b.addEventListener('click', () => { history.replaceState(null,'','#'+b.dataset.view); show(b.dataset.view); }));
window.addEventListener('hashchange', () => show(location.hash.slice(1)));
show(location.hash.slice(1) || 'overview');
"""


def build_dashboard(r, path: Path | None = None) -> Path:
    s = r.settings
    path = path or s.path("deliverables_dir") / "SupplierPulse_Dashboard.html"
    hl = r.headline
    k = r.kpis
    sk = r.syn_kpis
    figs = {
        "fig_family": chart_family(r), "fig_fy": chart_fy(r), "fig_dep": chart_category_dependency(r), "fig_pareto": chart_pareto(r),
        "fig_otif": chart_monthly_otif(r), "fig_quad": chart_perf_dependency(r), "fig_realloc": chart_realloc(r),
    }
    figs_json = "{" + ",".join(f'"{key}":{fig.to_json()}' for key, fig in figs.items()) + "}"
    period = hl["period_label"]
    as_of = pd.Timestamp(s.synthetic["as_of_date"])
    obs_note = (f"<div class='datanote'><b>Observed data</b> · City of Austin purchase orders, {period} "
                f"({hl['period_dates']}) · award values, not payments</div>")
    syn_note = (f"<div class='datanote'><b>Synthetic demonstration data</b> · {sk['suppliers']} anonymous suppliers "
                f"· as of {as_of:%d %b %Y}</div>")

    # ---------------- View 1 ----------------
    c = s.concentration
    exposures = f"""
    <ul class="findings">
      <li>In <b>{hl['single_vendor_categories']} categories</b> one vendor holds at least {c['single_vendor_share']:.0%} of spend
          ({money(hl['single_vendor_spend'])}). The largest is {esc(hl['largest_single_vendor_category'][4:])}:
          {hl['largest_single_vendor_share']:.0%} of {money(hl['largest_single_vendor_spend'])}. Exposures to review, not evidence of poor vendors.</li>
      <li><b>{hl['highly_concentrated_categories']} of {hl['screened_categories']}</b> categories over {money(c['min_category_spend'])} are highly
          concentrated (HHI &ge; {c['hhi_highly_concentrated']:,}), covering {money(hl['highly_concentrated_spend'])} of spend.</li>
      <li><b>Distribution transformer prices</b> rose a median {pct(hl['transformer_median_change_22_23'], 0)}
          (up to {pct(hl['transformer_max_change_22_23'], 0)}) for the same items between FY2022 and FY2023.</li>
      <li><b>{pct(k['master_agreement_share'])}</b> of spend flows through master agreements; the rest is one-off contracts and POs.</li>
    </ul>"""
    v1 = f"""
    <section class="view" id="overview">
      <div class="question"><h2>Where is the money going, and where is procurement exposure greatest?</h2>{obs_note}</div>
      <div class="tiles">
        {tile("Committed spend", money(k['total_spend']), f"{period}, 5 fiscal years")}
        {tile("Purchase orders", f"{k['po_count']:,}", f"{k['line_count']:,} order lines")}
        {tile("Active vendors", f"{k['active_vendors']:,}", f"{k['vendors_for_80pct']} vendors = 80% of spend")}
        {tile("Top 10 vendors", pct(k['top10_vendor_share']), "share of total spend")}
        {tile("On master agreements", pct(k['master_agreement_share']), "share of spend via delivery orders")}
      </div>
      <div class="grid g2">
        {card("Spend by category family", chart_div("fig_family"), "Where the money goes. Families group NIGP commodity classes.")}
        {card("Supplier dependency in the 15 largest categories", chart_div("fig_dep") +
              f'<div class="legend"><span><i class="sw" style="background:{CRIT}"></i>One vendor &ge; {c["single_vendor_share"]:.0%} (R1)</span>'
              f'<span><i class="sw" style="background:{WARN}"></i>Highly concentrated, HHI &ge; {c["hhi_highly_concentrated"]:,} (R2)</span>'
              f'<span><i class="sw" style="background:{SLATE}"></i>Not flagged</span></div>',
              "Share of each category's spend held by its largest vendor. Labels show share and category spend.")}
      </div>
      <div class="grid g32">
        {card("Spend by fiscal year", chart_div("fig_fy"), "FY2010-FY2026. Navy bars are the analysis window.")}
        {card("Major exposures", exposures)}
      </div>
      <div class="grid g2">
        {card("Vendor concentration (Pareto)", chart_div("fig_pareto"), "Cumulative share of spend by vendor rank.")}
        {card("Exception register", exception_summary(r), "Every flag has a written rule (docs/methodology.md).")}
      </div>
    </section>"""

    # ---------------- View 2 ----------------
    v2 = f"""
    <section class="view" id="performance">
      <div class="question"><h2>Which suppliers are reliable, which are not, and why?</h2>{syn_note}</div>
      <div class="synthetic-banner"><b>Synthetic demonstration.</b> The City of Austin data has no delivery or receipt dates, so delivery
        performance cannot be measured from it. This view uses a generated dataset of anonymous suppliers to show the method.
        It is not real-world supplier performance.</div>
      <div class="tiles">
        {tile("OTIF, all suppliers", pct(sk['otif_rate']), f"{sk['due_lines']:,} due PO lines")}
        {tile("OTIF trend", f"{pct(sk['otif_prior_12m'], 0)} → {pct(sk['otif_last_12m'], 0)}", "prior 12 months → last 12 months")}
        {tile("In full", pct(sk['in_full_rate']), f"{sk['short_closed_lines']} lines closed short")}
        {tile("Quality reject rate", pct(sk['reject_rate'], 2), "rejected / received units")}
        {tile("Overdue open lines", f"{sk['overdue_lines']}", f"{money(sk['overdue_value'])} still outstanding")}
      </div>
      {card("Supplier scorecard", scorecard_table(r),
            "Score = OTIF 40% + quality 25% + lead-time consistency 20% + lateness 15%, each scaled 0-100 between a 'poor' and a 'target' value. "
            "Ranked only with 30+ due lines; ties share a rank.")}
      <div style="height:16px"></div>
      <div class="grid g2">
        {card("Performance vs dependency", chart_div("fig_quad"),
              "Keeps reliability and dependency separate. Open circle = provisional sample (10-29 due lines).")}
        {card("Monthly OTIF, all suppliers", chart_div("fig_otif"), "Share of due lines delivered complete by the promised date.")}
      </div>
    </section>"""

    # ---------------- View 3 ----------------
    rr = r.realloc[r.realloc["share_moved"].round(2) == 0.30]
    scen_txt = ""
    if len(rr):
        x = rr.iloc[0]
        scen_txt = (f"<p>Moving <b>30%</b> of {esc(x['from_supplier'])}'s {esc(x['category_id'])} volume to {esc(x['to_supplier'])} "
                    f"would avoid an estimated <b>{x['late_lines_avoided']:.0f} of {x['late_lines_before']:.0f}</b> late lines a year "
                    f"and lower its category share from {pct(r.scorecard.set_index('supplier_id').loc[x['from_supplier'], 'max_category_share'], 0)} "
                    f"to {pct(x['from_share_after'], 0)}. At an assumed ${x['cost_per_late_line']:.0f} per late line, that is "
                    f"{money(x['late_cost_avoided'])} a year in handling cost; prices move by {money(x['price_impact'])} a year "
                    f"({'cheaper' if x['price_impact'] < 0 else 'more expensive'} at the alternative's current prices).</p>"
                    "<p class='small'>Modelled, not realised. Assumes the alternative keeps its current OTIF and price at higher volume; "
                    "confirm capacity first.</p>")
    ph = r.price_scenario
    price_rows = "".join(f"<tr><td class='num'>{x.capture_rate:.0%}</td><td class='num'>{money(x.modelled_opportunity)}</td></tr>" for x in ph.itertuples())
    v3 = f"""
    <section class="view" id="decisions">
      <div class="question"><h2>Which issues require action, and what should the company do?</h2>
        <div class="datanote">Each action is labelled <b>Observed</b> (City of Austin) or <b>Synthetic</b> (method demonstration)</div></div>
      {card("Prioritised action list", action_table(r), f"Top 12 of {len(r.actions)} actions, highest priority first. Full list in the Excel workbook (Action_List).")}
      <div style="height:16px"></div>
      <div class="grid g2">
        {card("Scenario: rebalance volume away from the critical supplier", chart_div("fig_realloc") + scen_txt, "Synthetic demonstration · last 12 months of volume")}
        {card("Scenario: harmonise like-for-like prices", f"<p>If the {hl['price_flagged_lines']} purchase lines priced at 1.5x or more of the same item's median "
              f"in that fiscal year had been bought at the median, spend would have been lower by:</p>"
              f"<table class='tbl compact'><thead><tr><th>Share captured</th><th>Modelled amount, {period} total</th></tr></thead><tbody>{price_rows}</tbody></table>"
              f"<p class='small'>Observed City of Austin prices. Covers only the {pct(hl['comparable_share_of_spend'], 0)} of spend that is like-for-like comparable. "
              f"Counting only orders of similar size (0.5x-2x the item's median quantity) the full amount is {money(hl['price_opportunity_qty_controlled'])}. "
              "Differences may reflect urgency, order size or market timing; this is an opportunity to investigate, not a saving.</p>"
              + "<h3 style='margin-top:14px'>Overdue open PO lines (synthetic)</h3>" + overdue_table(r))}
      </div>
    </section>"""

    body = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>SupplierPulse Dashboard</title>
<meta name="description" content="SupplierPulse: supplier performance and procurement analytics dashboard (observed City of Austin spend and a synthetic delivery-performance demonstration).">
<style>{CSS}</style>
<script>{get_plotlyjs()}</script>
</head><body>
<header>
  <div class="brand">
    <div><h1>SupplierPulse</h1><div class="subtitle">Supplier Performance &amp; Procurement Analytics</div></div>
    <div class="meta">Observed: City of Austin Open Data, {period} · Synthetic: deterministic demonstration (seed {sk['seed']})</div>
  </div>
  <nav>
    <button data-view="overview">1 · Procurement Overview</button>
    <button data-view="performance">2 · Supplier Performance</button>
    <button data-view="decisions">3 · Procurement Decisions</button>
  </nav>
</header>
<main>{v1}{v2}{v3}</main>
<footer>Source: City of Austin, "Purchase Order Quantity Price detail for Commodity/Goods procurements" (data.austintexas.gov, dataset 3ebq-e9iz),
snapshot built {esc(', '.join(r.clean.audit['source_build_dates']))}. Spend = awarded PO line value. Synthetic suppliers are fictional. Modelled values are estimates, not realised savings.
Built by Harjot Sandhu.</footer>
<script>{JS.replace("__FIGS__", figs_json)}</script>
</body></html>"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path
