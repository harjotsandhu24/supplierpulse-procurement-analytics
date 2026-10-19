"""Audit gaps: duplicate sensitivity, KPI reconciliation across dashboard / Python / SQL, offline
rendering, PDF content and documentation links."""

import re
import subprocess
import sys
from pathlib import Path

import pytest

from supplierpulse import spend
from supplierpulse.dashboard import money, pct

ROOT = Path(__file__).resolve().parents[1]
DASH = ROOT / "deliverables" / "SupplierPulse_Dashboard.html"
PDF = ROOT / "deliverables" / "SupplierPulse_Decision_Brief.pdf"


def _flags(lines, settings):
    c = settings.concentration
    cat = spend.category_concentration(lines)
    big = cat[cat["spend"] >= c["min_category_spend"]]
    v = spend.vendor_spend(lines)
    return {
        "r1": sorted(big.loc[big["top_vendor_share"] >= c["single_vendor_share"], "nigp_class"]),
        "hhi": int((big["hhi"] >= c["hhi_highly_concentrated"]).sum()),
        "v80": int((v["cumulative_share"] < 0.80).sum() + 1),
        "largest": round(float(v["share"].iloc[0]), 4),
        "fuel": round(float(big.set_index("nigp_class").loc["405", "top_vendor_share"]), 4),
    }


def test_conclusions_do_not_depend_on_duplicate_rows(results, settings):
    lines = results.model.lines
    dups = lines["possible_duplicate"] & lines["in_focus_window"]
    assert 0 < dups.sum() < 20
    assert _flags(lines, settings) == _flags(lines[~lines["possible_duplicate"]], settings)


def test_dashboard_kpis_reconcile_with_python_and_sql(results, sql):
    html = DASH.read_text(encoding="utf-8")
    k, sk = results.kpis, results.syn_kpis
    sql_total = sql.execute("SELECT SUM(line_amount) FROM v_obs_focus_line").fetchone()[0]
    sql_pos = sql.execute("SELECT COUNT(DISTINCT purchase_order) FROM v_obs_focus_line").fetchone()[0]
    sql_vendors = sql.execute("SELECT COUNT(DISTINCT vendor_code) FROM v_obs_focus_line").fetchone()[0]
    sql_otif = sql.execute("SELECT AVG(CASE WHEN otif THEN 1.0 ELSE 0.0 END) FROM v_syn_line_delivery WHERE due").fetchone()[0]
    assert money(sql_total) == money(k["total_spend"]) and sql_pos == k["po_count"] and sql_vendors == k["active_vendors"]
    for shown in [money(k["total_spend"]), f"{k['po_count']:,}", f"{k['active_vendors']:,}", pct(k["top10_vendor_share"]),
                  pct(k["master_agreement_share"]), pct(sk["otif_rate"]), pct(sql_otif), f"{k['vendors_for_80pct']} vendors = 80% of spend"]:
        assert f">{shown}<" in html or shown in html, shown


def test_dashboard_works_offline_and_every_view_renders(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="msedge")
        except Exception:  # noqa: BLE001
            try:
                browser = p.chromium.launch()
            except Exception:  # noqa: BLE001
                pytest.skip("no browser available")
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        external, errors = [], []
        page.route("**/*", lambda route: route.continue_() if route.request.url.startswith("file:") else (external.append(route.request.url), route.abort()))
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(DASH.as_uri())
        counts = {}
        for view in ["overview", "performance", "decisions"]:
            page.click(f"nav button[data-view='{view}']")
            page.wait_for_function(f"document.body.dataset.ready === '{view}'")
            page.wait_for_timeout(300)
            counts[view] = page.locator(f"#{view} .main-svg").count()
            assert page.locator(f"#{view}").is_visible()
        page.evaluate("Plotly.Fx.hover('fig_realloc', [{curveNumber: 0, pointNumber: 3}])")
        page.wait_for_timeout(300)
        hover = page.locator(".hoverlayer .hovertext").count()
        browser.close()
    assert not external, external
    assert not errors, errors
    assert counts["overview"] >= 4 and counts["performance"] >= 2 and counts["decisions"] >= 1, counts
    assert hover >= 1


def test_pdf_brief_matches_final_analysis(results):
    pypdf = pytest.importorskip("pypdf")
    if not PDF.exists():
        pytest.skip("PDF not rendered (run the pipeline with --render)")
    reader = pypdf.PdfReader(str(PDF))
    assert len(reader.pages) == 1
    text = re.sub(r"\s+", " ", reader.pages[0].extract_text())
    hl, k = results.headline, results.kpis
    for expected in [money(k["total_spend"]), f"{k['vendors_for_80pct']}", f"{hl['highly_concentrated_categories']} of {hl['screened_categories']}",
                     f"{hl['largest_single_vendor_share']:.0%} of {money(hl['largest_single_vendor_spend'])}",
                     f"median {pct(hl['transformer_median_change_22_23'], 0)}", "Synthetic", "Observed"]:
        assert expected in text, expected


def test_documentation_links_resolve():
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_links.py")], capture_output=True, text=True, cwd=ROOT)
    assert out.returncode == 0, out.stdout


def test_ci_workflow_is_valid_and_runs_the_suite():
    yaml = pytest.importorskip("yaml")
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    steps = " ".join(str(s.get("run", "")) for s in wf["jobs"]["test"]["steps"])
    assert "pip install -r requirements-dev.txt" in steps and "supplierpulse.pipeline" in steps and "pytest" in steps
