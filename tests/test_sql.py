"""SQL package: every query runs, and SQL results agree with the pandas implementation."""

import pandas as pd
import pytest

from supplierpulse import database


@pytest.fixture(scope="module")
def q(settings, db, tmp_path_factory):
    return database.run_queries(settings, tmp_path_factory.mktemp("sql"))


def test_all_queries_run_and_return_rows(q, settings):
    files = database.query_files(settings)
    assert len(files) == 12
    for f in files:
        assert len(q[f.stem]) > 0, f.stem


def test_every_query_documents_its_question(settings):
    for f in database.query_files(settings):
        head = f.read_text(encoding="utf-8").splitlines()[:3]
        assert head[0].startswith("-- Q") and "?" in head[0], f.name
        assert any("Data:" in line for line in head), f.name


def test_top_vendors_and_concentration(q, results):
    top = q["01_top_vendors_by_spend"]
    py = results.vendors.head(15)
    assert top["vendor_code"].tolist() == py["vendor_code"].tolist()
    assert top["spend"].to_numpy() == pytest.approx(py["spend"].round(2).to_numpy())
    c = q["02_vendor_concentration"].iloc[0]
    assert c["vendor_hhi"] == pytest.approx(results.kpis["vendor_hhi"])
    assert c["vendors_for_80pct"] == results.kpis["vendors_for_80pct"]
    assert c["total_spend"] == pytest.approx(results.kpis["total_spend"], abs=0.01)


def test_category_dependency_flags_match(q, results, settings):
    sql = q["04_category_dependency"]
    c = settings.concentration
    py = results.categories[results.categories["spend"] >= c["min_category_spend"]]
    assert len(sql) == len(py)
    sql_r1 = set(sql.loc[sql["dependency_flag"].str.startswith("R1"), "nigp_class"])
    assert sql_r1 == set(py.loc[py["top_vendor_share"] >= c["single_vendor_share"], "nigp_class"])
    merged = sql.set_index("nigp_class").join(py.set_index("nigp_class")[["hhi"]], rsuffix="_py")
    assert merged["hhi"].to_numpy() == pytest.approx(merged["hhi_py"].to_numpy())


def test_family_trend_matches(q, results):
    sql = q["03_category_spend_trend"].pivot(index="spend_family", columns="fiscal_year", values="spend")
    py = results.family_trend.reindex(sql.index)[sql.columns]
    assert sql.to_numpy() == pytest.approx(py.round(2).to_numpy(), abs=0.01)


def test_price_variance_matches(q, results):
    sql = q["06_price_variance_comparable_items"]
    assert sql["flagged_lines"].sum() == results.prices.summary["flagged_lines"]
    assert sql["excess_vs_baseline"].sum() == pytest.approx(results.prices.summary["modelled_opportunity_full"], abs=1)


def test_delivery_and_lead_time_match(q, results):
    sc = results.scorecard.set_index("supplier_id")
    d = q["07_supplier_delivery_performance"].set_index("supplier_id").reindex(sc.index)
    for col in ["otif_rate", "on_time_rate", "in_full_rate"]:
        assert d[col].to_numpy() == pytest.approx(sc[col].to_numpy())
    assert (d["due_lines"] == sc["due_lines"]).all()
    lt = q["08_lead_time_variability"].set_index("supplier_id").reindex(sc.index)
    perf = results.performance.set_index("supplier_id").reindex(sc.index)
    assert lt["lead_time_sd"].to_numpy() == pytest.approx(perf["lead_time_sd"].to_numpy())


def test_overdue_trend_scorecard_and_quadrants_match(q, results):
    assert len(q["09_open_overdue_lines"]) == results.syn_kpis["overdue_lines"]
    sc = results.scorecard.set_index("supplier_id")
    s = q["10_supplier_scorecard"].set_index("supplier_id").reindex(sc.index)
    assert s["performance_score"].fillna(-1).to_numpy() == pytest.approx(sc["performance_score"].fillna(-1).to_numpy(), abs=0.05)
    assert (s["score_rank"].fillna(-1).astype(int) == sc["rank"].fillna(-1).astype(int)).all()
    t = q["11_otif_trend_prior_vs_last_12m"].set_index("supplier_id").reindex(sc.index)
    assert t["otif_last_12m"].fillna(-1).to_numpy() == pytest.approx(sc["otif_last_12m"].fillna(-1).to_numpy())
    quad = q["12_procurement_risk_prioritization"].set_index("supplier_id").reindex(sc.index)
    assert (quad["action_quadrant"] == sc["action_quadrant"]).all()
    assert (quad["dependency_risk"] == sc["dependency_risk"]).all()


def test_views_do_not_inflate_rows(sql, results):
    n_focus = sql.execute("SELECT COUNT(*) FROM v_obs_focus_line").fetchone()[0]
    assert n_focus == int(results.model.lines["in_focus_window"].sum())
    n_lines = sql.execute("SELECT COUNT(*) FROM v_syn_line_delivery").fetchone()[0]
    assert n_lines == len(results.syn.po_lines)
