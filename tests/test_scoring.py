"""Scorecard: component scaling, weights, missing data, evidence thresholds, ties and dependency."""

import numpy as np
import pandas as pd
import pytest

from supplierpulse import scoring


def perf_row(**kw):
    base = dict(supplier_id="S", due_lines=100, completed_lines=100, otif_rate=0.95, reject_rate=0.005,
                lead_time_sd=2.0, avg_days_late_all_due=0.0, suppliers_in_category=3, max_category_share=0.2,
                share_of_total_spend=0.05)
    base.update(kw)
    return base


def score(settings, rows):
    return scoring.build_scorecard(pd.DataFrame(rows), settings).set_index("supplier_id")


def test_scale_endpoints_and_clipping():
    assert scoring.scale(0.95, 0.95, 0.70, True) == 100
    assert scoring.scale(0.70, 0.95, 0.70, True) == 0
    assert scoring.scale(0.825, 0.95, 0.70, True) == pytest.approx(50)
    assert scoring.scale(0.50, 0.95, 0.70, True) == 0      # clipped
    assert scoring.scale(0.0, 0.005, 0.05, False) == 100   # better than target clipped to 100
    assert np.isnan(scoring.scale(float("nan"), 1, 0, True))


def test_hand_calculated_score(settings):
    # OTIF 0.825 -> 50; reject 0.0275 -> 50; SD 4.5 -> 50; days late 2.5 -> 50  => 50 overall
    sc = score(settings, [perf_row(otif_rate=0.825, reject_rate=0.0275, lead_time_sd=4.5, avg_days_late_all_due=2.5)])
    assert sc.loc["S", "performance_score"] == pytest.approx(50.0)
    # OTIF perfect (100), others 0: 0.40 * 100 = 40
    sc = score(settings, [perf_row(otif_rate=1.0, reject_rate=0.2, lead_time_sd=20, avg_days_late_all_due=20)])
    assert sc.loc["S", "performance_score"] == pytest.approx(40.0)


def test_missing_component_is_reweighted_not_penalised(settings):
    # Too few completed lines -> lead-time variability missing; remaining weights renormalised
    sc = score(settings, [perf_row(completed_lines=5, lead_time_sd=50.0)])
    row = sc.loc["S"]
    assert row["reweighted"] and row["weight_used"] == pytest.approx(0.80)
    assert np.isnan(row["score_leadtime_consistency"])
    assert row["performance_score"] == pytest.approx(100.0)


def test_evidence_thresholds(settings):
    sc = score(settings, [perf_row(supplier_id="A", due_lines=9), perf_row(supplier_id="B", due_lines=10),
                          perf_row(supplier_id="C", due_lines=29), perf_row(supplier_id="D", due_lines=30)])
    assert sc.loc["A", "evidence_status"] == "Insufficient evidence" and np.isnan(sc.loc["A", "performance_score"])
    assert sc.loc["B", "evidence_status"] == "Provisional" and pd.isna(sc.loc["B", "rank"])
    assert sc.loc["C", "evidence_status"] == "Provisional"
    assert sc.loc["D", "evidence_status"] == "Ranked" and sc.loc["D", "rank"] == 1


def test_ties_share_rank_and_next_rank_skips(settings):
    sc = score(settings, [perf_row(supplier_id="A"), perf_row(supplier_id="B"), perf_row(supplier_id="C", otif_rate=0.8)])
    assert sc.loc["A", "rank"] == 1 and sc.loc["B", "rank"] == 1 and sc.loc["C", "rank"] == 3


def test_small_sample_cannot_outrank_large_sample(settings):
    sc = score(settings, [perf_row(supplier_id="BIG", otif_rate=0.90), perf_row(supplier_id="TINY", due_lines=12, otif_rate=1.0)])
    assert sc.loc["BIG", "rank"] == 1 and pd.isna(sc.loc["TINY", "rank"])


def test_dependency_and_quadrant(settings):
    sc = score(settings, [
        perf_row(supplier_id="SOLE", suppliers_in_category=1, max_category_share=1.0),
        perf_row(supplier_id="POOR_DEP", max_category_share=0.7, otif_rate=0.7, reject_rate=0.05, lead_time_sd=7, avg_days_late_all_due=5),
        perf_row(supplier_id="MED", max_category_share=0.4),
        perf_row(supplier_id="LOW", max_category_share=0.1, share_of_total_spend=0.01),
    ])
    assert sc.loc["SOLE", "dependency_risk"] == "High" and sc.loc["SOLE", "action_quadrant"] == "Strategic - protect and monitor"
    assert sc.loc["POOR_DEP", "action_quadrant"] == "Critical - act now"
    assert sc.loc["MED", "dependency_risk"] == "Medium"
    assert sc.loc["LOW", "dependency_risk"] == "Low"


def test_published_scorecard_is_explainable(results, settings):
    sc = results.scorecard
    w = settings.scorecard
    ranked = sc[sc["evidence_status"] == "Ranked"]
    comps = ["score_otif", "score_quality", "score_leadtime_consistency", "score_lateness"]
    weights = [w["weight_otif"], w["weight_quality"], w["weight_leadtime_consistency"], w["weight_lateness"]]
    for _, row in ranked.iterrows():
        used = [(row[c], wt) for c, wt in zip(comps, weights) if not np.isnan(row[c])]
        manual = sum(v * wt for v, wt in used) / sum(wt for _, wt in used)
        assert row["performance_score"] == pytest.approx(round(manual, 1), abs=0.05)
