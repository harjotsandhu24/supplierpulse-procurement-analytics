"""Scenario arithmetic, exception rules and the action list."""

import pandas as pd
import pytest

from supplierpulse import delivery, scenarios
from tests.conftest import MINI_AS_OF


def test_reallocation_reconciles(results, settings):
    rr = results.realloc
    assert not rr.empty
    base = rr[rr["share_moved"] == 0].iloc[0]
    assert base["late_lines_avoided"] == pytest.approx(0) and base["price_impact"] == pytest.approx(0)
    vol = scenarios.last_12m_volumes(results.facts, base["category_id"]).set_index("supplier_id")
    lf = vol.at[base["from_supplier"], "due_lines"]
    for _, row in rr.iterrows():
        # closed form: x * L_from * (OTIF_to - OTIF_from)
        assert row["late_lines_avoided"] == pytest.approx(row["share_moved"] * lf * (row["otif_to"] - row["otif_from"]))
        assert row["late_cost_avoided"] == pytest.approx(row["late_lines_avoided"] * settings.scenario["cost_per_late_line"])
        assert row["net_modelled_benefit"] == pytest.approx(row["late_cost_avoided"] - row["price_impact"])
    # moving volume to a better supplier reduces the incumbent's share monotonically
    assert rr["from_share_after"].is_monotonic_decreasing


def test_reallocation_preserves_total_spend(results):
    rr = results.realloc
    vol = scenarios.last_12m_volumes(results.facts, rr.iloc[0]["category_id"])
    total = vol["spend"].sum()
    for _, row in rr.iterrows():
        assert row["spend_moved"] <= total
        assert 0 <= row["from_share_after"] <= 1


def test_otif_improvement_never_negative_and_zero_at_target(results, settings):
    o = results.otif_scenario
    assert (o["late_lines_avoided"] >= -1e-9).all()
    at_target = o[o["otif_basis"] >= settings.scorecard["otif_target"]]
    assert (at_target["late_lines_avoided"].abs() < 1e-9).all()


def test_price_harmonisation_is_linear(results):
    p = results.price_scenario
    full = results.prices.summary["modelled_opportunity_full"]
    assert (p["modelled_opportunity"] - p["capture_rate"] * full).abs().max() < 1e-6


def test_exception_rules_are_auditable(results, settings):
    reg = results.register
    assert reg["exception_id"].is_unique
    assert set(reg["rule"]) <= set(results.definitions["rule"])
    s1 = reg[reg["rule"] == "S1"]
    sc = results.scorecard.set_index("supplier_id")
    for _, row in s1.iterrows():
        assert sc.loc[row["entity_id"], "otif_rate"] < settings.exceptions["chronic_late_otif"]
        assert sc.loc[row["entity_id"], "due_lines"] >= settings.exceptions["min_lines_for_rate_flags"]
    expected_s1 = sc[(sc["otif_rate"] < settings.exceptions["chronic_late_otif"])
                     & (sc["due_lines"] >= settings.exceptions["min_lines_for_rate_flags"])].index
    assert set(s1["entity_id"]) == set(expected_s1)
    assert (reg["rule"] == "S7").sum() == results.syn_kpis["overdue_lines"]


def test_actions_are_labelled_and_never_mix_sources(results):
    a = results.actions
    assert a["action_id"].is_unique
    assert set(a["priority"]) <= {"High", "Medium", "Low"}
    assert a["data_limitation"].str.len().gt(10).all()
    syn = a[a["data_origin"].str.startswith("Synthetic")]
    obs = a[a["data_origin"].str.startswith("Observed")]
    assert syn["data_limitation"].str.contains("Synthetic").all()
    assert not obs["supplier_or_category"].str.contains(r"SUP-\d\d").any()
    real_names = set(results.model.vendors["vendor_name"].str.upper())
    for text in syn[["supplier_or_category", "supporting_metric", "recommended_action"]].to_numpy().ravel():
        assert not any(name in text.upper() for name in real_names if len(name) > 6)
    # priorities are ordered High -> Medium -> Low
    order = a["priority"].map({"High": 1, "Medium": 2, "Low": 3})
    assert order.is_monotonic_increasing


def test_no_unsupported_savings_language(results):
    text = " ".join(results.actions.astype(str).to_numpy().ravel()).lower()
    assert "guarantee" not in text and "will save" not in text


def test_mini_scenario_hand_check(mini, settings):
    f = delivery.line_facts(mini, MINI_AS_OF)
    f["due_period"] = "last_12m"
    rr = scenarios.reallocation(f, "X", "A", "B", settings)
    half = rr[rr["share_moved"] == 0.5].iloc[0]
    # A: 4 due, OTIF 0.25; B: 1 due, OTIF 0 -> moving half of A's lines to B adds late lines
    assert half["late_lines_avoided"] == pytest.approx(0.5 * 4 * (0.0 - 0.25))
    assert half["price_impact"] > 0  # B's paid price is 10% above contract, A's is at contract
