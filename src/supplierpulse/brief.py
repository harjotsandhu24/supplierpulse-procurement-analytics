"""One-page executive decision brief (HTML source -> PDF/PNG via render.py).

Every number is taken from the pipeline results, so the brief cannot drift from the analysis.
"""

from __future__ import annotations

from pathlib import Path

import plotly.graph_objects as go
from plotly.offline import get_plotlyjs

from .dashboard import FONT, INK, MUTED, NAVY, esc, money, pct


def top_three(r) -> list[dict]:
    a = r.actions
    picks = []
    obs = a[a["data_origin"].str.startswith("Observed") & (a["priority"] == "High")]
    dep = obs[obs["issue"].str.startswith("Single-vendor concentration")]
    price = obs[obs["issue"] == "Sharp year-over-year price increases"]
    syn = a[a["data_origin"].str.startswith("Synthetic") & (a["priority"] == "High")]
    for df in (dep, price, syn):
        if len(df):
            picks.append(df.iloc[0].to_dict())
    return picks


def _chart(r) -> str:
    c = r.settings.concentration
    big = r.categories[(r.categories["spend"] >= c["min_category_spend"]) & (r.categories["top_vendor_share"] >= c["single_vendor_share"])]
    big = big.sort_values("spend")
    labels = [lab[4:38] + ("…" if len(lab) > 38 else "") for lab in big["class_label"]]
    fig = go.Figure(go.Bar(
        x=big["spend"] / 1e6, y=labels, orientation="h", marker=dict(color=NAVY, cornerradius=2),
        text=[f"{money(v)} · {s:.0%}" for v, s in zip(big["spend"], big["top_vendor_share"])],
        textposition="outside", cliponaxis=False, textfont=dict(size=10, color=INK),
    ))
    fig.update_layout(height=150, margin=dict(l=4, r=8, t=4, b=22), paper_bgcolor="white", plot_bgcolor="white",
                      font=dict(family=FONT, size=10, color=INK), showlegend=False)
    fig.update_xaxes(range=[0, big["spend"].max() / 1e6 * 1.45], gridcolor="#E2E8F0", tickfont=dict(color=MUTED, size=9),
                     title=dict(text="FY2022-26 spend, $M", font=dict(size=9, color=MUTED)))
    fig.update_yaxes(tickfont=dict(size=10))
    return fig.to_json()


CSS = """
@page{size:Letter;margin:0.35in 0.4in}
*{box-sizing:border-box}
body{margin:0;font-family:"Segoe UI",-apple-system,Arial,sans-serif;color:#0F172A;font-size:10.4px;line-height:1.38;background:#fff}
.page{max-width:7.7in;margin:0 auto}
h1{font-size:19px;margin:0;color:#1F2A44}
.sub{color:#475569;font-size:10.5px;margin-top:2px}
.notice{margin:8px 0 8px;padding:6px 9px;border-left:3px solid #475569;background:#F6F8FA;font-size:10px;color:#334155}
h2{font-size:11.5px;color:#1F2A44;margin:9px 0 3px;text-transform:uppercase;letter-spacing:.5px;border-bottom:1px solid #E2E8F0;padding-bottom:2px}
.two{display:grid;grid-template-columns:1fr 1fr;gap:14px}
ul{margin:2px 0;padding-left:15px}li{margin:2px 0}
.tag{font-size:8.5px;border:1px solid #CBD5E1;border-radius:3px;padding:0 4px;color:#475569;margin-right:4px;white-space:nowrap}
.tag.o{border-color:#9FB4CC;color:#1F2A44}
table{width:100%;border-collapse:collapse;font-size:10px}
th{text-align:left;color:#475569;font-weight:600;border-bottom:1.5px solid #CBD5E1;padding:3px 5px}
td{border-bottom:1px solid #E2E8F0;padding:4px 5px;vertical-align:top}
.n{font-weight:700;color:#1F2A44;font-size:12px}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:6px 0 2px}
.kpi{border:1px solid #E2E8F0;border-radius:5px;padding:5px 7px}
.kpi b{display:block;font-size:15px;color:#1F2A44}
.kpi span{font-size:9px;color:#64748B}
.foot{margin-top:8px;font-size:8.5px;color:#64748B}
"""


def build_brief(r, path: Path | None = None) -> Path:
    s = r.settings
    path = path or s.path("deliverables_dir") / "SupplierPulse_Decision_Brief.html"
    hl, k, sk = r.headline, r.kpis, r.syn_kpis
    c = s.concentration
    acts = top_three(r)
    r1 = r.register[(r.register["rule"] == "R1") & r.register["detail"].str.contains("(recurring)", regex=False)]
    dep_examples = ", ".join(n[4:].split(",")[0].lower() for n in r1["entity_name"].head(3))
    O = '<span class="tag o">Observed</span>'
    S = '<span class="tag">Synthetic</span>'
    rows = ""
    for i, a in enumerate(acts, start=1):
        tag = O if a["data_origin"].startswith("Observed") else S
        metric = esc(a["supporting_metric"]).replace("&gt;= ", "≥ ").replace(" -&gt; ", " → ")
        rows += (f"<tr><td class='n'>{i}</td><td><b>{esc(a['supplier_or_category'])}</b><br>{tag}{esc(a['issue'])}</td>"
                 f"<td>{metric}</td><td>{esc(a['recommended_action'])}</td></tr>")
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>SupplierPulse Decision Brief</title>
<style>{CSS}</style><script>{get_plotlyjs()}</script></head><body><div class="page">
<h1>SupplierPulse — Procurement Performance Review</h1>
<div class="sub">Supplier performance, spend concentration and purchasing risk · Harjot Sandhu · analysis window {hl['period_label']} ({hl['period_dates']})</div>
<div class="notice"><b>Two kinds of evidence.</b> Spend, concentration and price findings use <b>observed</b> City of Austin purchase-order data.
That data has no delivery dates, so delivery, quality and scorecard findings use a clearly labelled <b>synthetic</b> demonstration dataset
of anonymous suppliers. Synthetic results show the method; they are not real-world supplier performance.</div>

<div class="two">
<div>
<h2>1. What was analysed</h2>
Which suppliers are reliable, where purchasing spend and dependency are concentrated, where prices for identical items are inconsistent,
and which issues procurement should act on first.
<h2>2. Data used</h2>
<ul>
<li>{O}City of Austin Open Data: {k['line_count']:,} goods PO lines, {k['po_count']:,} POs, {k['active_vendors']:,} vendors, {money(k['total_spend'])} awarded value.</li>
<li>{S}{sk['suppliers']} anonymous suppliers, {sk['po_lines']:,} PO lines and {sk['receipts']:,} goods receipts (deterministic, seed {sk['seed']}).</li>
</ul>
</div>
<div>
<div class="kpis">
<div class="kpi"><b>{money(k['total_spend'])}</b><span>spend {hl['period_label']}</span></div>
<div class="kpi"><b>{k['vendors_for_80pct']}</b><span>vendors = 80% of spend</span></div>
<div class="kpi"><b>{hl['single_vendor_categories']}</b><span>single-vendor categories</span></div>
<div class="kpi"><b>{pct(k['master_agreement_share'], 0)}</b><span>spend on master agreements</span></div>
</div>
<div style="font-size:9.5px;color:#475569;margin-top:4px">Categories where one vendor holds ≥ {c['single_vendor_share']:.0%} of spend {O}</div>
<div id="chart"></div>
</div>
</div>

<h2>3. Most important supported findings</h2>
<ul>
<li>{O}<b>Dependency is concentrated, not spend overall.</b> The largest vendor holds only {pct(r.vendors['share'].max())} of total spend, but
{hl['highly_concentrated_categories']} of {hl['screened_categories']} categories over $1M are highly concentrated (HHI ≥ {c['hhi_highly_concentrated']:,}),
and in {hl['single_vendor_categories']} one vendor holds ≥ {c['single_vendor_share']:.0%} ({money(hl['single_vendor_spend'])}). The largest is fuel:
{hl['largest_single_vendor_share']:.0%} of {money(hl['largest_single_vendor_spend'])}, bought on recurring orders.</li>
<li>{O}<b>Identical items got sharply more expensive.</b> Distribution-transformer prices rose a median {pct(hl['transformer_median_change_22_23'], 0)}
(up to {pct(hl['transformer_max_change_22_23'], 0)}) from FY2022 to FY2023, consistent with the industry-wide transformer shortage.</li>
<li>{O}<b>Same-item price dispersion:</b> {hl['price_flagged_lines']} lines were priced ≥ 1.5× the item's median in the same year
({money(hl['price_opportunity_qty_controlled'])}–{money(hl['price_opportunity_full'])} above median over five years, the lower figure with order size held comparable;
modelled, covering {pct(hl['comparable_share_of_spend'], 0)} of spend).</li>
<li>{S}<b>The method flags a deteriorating critical supplier:</b> {esc(hl['critical_supplier'])} holds {pct(hl['critical_category_share'], 0)} of its category,
yet OTIF fell from {pct(hl['critical_otif_prior'], 0)} to {pct(hl['critical_otif_last'], 0)}; score {hl['critical_supplier_score']:.0f}/100.</li>
</ul>

<h2>4. Business risks identified</h2>
<ul>
<li><b>Supply continuity:</b> where one vendor dominates a category ({esc(dep_examples)}), the purchasing record shows no established alternative at scale; this warrants review, not a conclusion about the vendor.</li>
<li><b>Budget exposure:</b> long-lead electrical equipment repriced by a median {pct(hl['transformer_median_change_22_23'], 0)} (up to {pct(hl['transformer_max_change_22_23'], 0)}) in one year.</li>
<li><b>Negotiating leverage:</b> high concentration in large categories weakens competition at renewal.</li>
</ul>

<h2>5. Three actions to prioritise</h2>
<table><thead><tr><th>#</th><th>Where</th><th>Evidence</th><th>Recommended action</th></tr></thead><tbody>{rows}</tbody></table>

<h2>6. Limitations</h2>
<ul>
<li>Austin "spend" is awarded PO value, not invoices or payments; cancellations after award are not visible.</li>
<li>No delivery, receipt or quality data exists in the public source, so no real supplier is rated on delivery.</li>
<li>Concentration can be a deliberate result of competitive bidding; price differences may reflect urgency, quantity or specification.</li>
<li>Modelled amounts (price harmonisation, scenarios) are opportunities to investigate, not realised savings.</li>
</ul>
<div class="foot">Source: City of Austin Open Data, dataset 3ebq-e9iz (data.austintexas.gov), snapshot built {esc(', '.join(r.clean.audit['source_build_dates']))};
offered free and without restriction under the City of Austin Open Data Terms of Use. Full methodology: github repository docs/methodology.md.</div>
</div>
<script>
const f = {_chart(r)};
Plotly.newPlot('chart', f.data, f.layout, {{displayModeBar:false, staticPlot:true}}).then(() => {{ document.body.dataset.ready = 'yes'; }});
</script>
</body></html>"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return path
