"""Delivery metrics: denominators, partial receipts, cancellations and missing receipts."""

import pandas as pd
import pytest

from supplierpulse import delivery
from tests.conftest import MINI_AS_OF


@pytest.fixture
def facts(mini):
    return delivery.line_facts(mini, MINI_AS_OF).set_index("po_line_id")


def test_full_on_time_line(facts):
    l1 = facts.loc["L1"]
    assert l1.due and l1.on_time and l1.in_full and l1.otif
    assert l1.days_late == 0 and l1.lead_time_days == 13


def test_partial_receipt_is_on_time_but_not_otif(facts):
    l2 = facts.loc["L2"]
    assert l2.on_time and l2.in_full and not l2.otif
    assert l2.qty_by_promise == 6 and l2.received_qty == 10
    assert l2.completion_date == pd.Timestamp("2026-01-20")
    assert l2.days_late == 5


def test_cancelled_line_excluded(facts):
    l3 = facts.loc["L3"]
    assert not l3.due and not l3.open and l3.status == "Cancelled"
    assert pd.isna(l3.days_late)


def test_not_yet_due_line_is_not_counted_as_success_or_failure(facts):
    l4 = facts.loc["L4"]
    assert not l4.due and not (l4.on_time or l4.in_full or l4.otif)
    assert l4.open and not l4.overdue


def test_missing_receipts_never_create_on_time_results(facts):
    l5 = facts.loc["L5"]
    assert l5.due and not (l5.on_time or l5.in_full or l5.otif)
    assert l5.open and l5.overdue
    assert l5.days_late == (MINI_AS_OF - pd.Timestamp("2026-02-28")).days


def test_short_closed_line_fails_in_full_and_is_not_open(facts):
    l6 = facts.loc["L6"]
    assert l6.on_time and not l6.in_full and not l6.otif
    assert not l6.open and not l6.overdue and l6.status == "Closed short"
    assert l6.days_late == 0


def test_supplier_denominators(facts):
    perf = delivery.supplier_performance(facts.reset_index()).set_index("supplier_id")
    a = perf.loc["A"]
    assert a.due_lines == 4                      # L1, L2, L5, L6 (not L3 cancelled, not L4 not-yet-due)
    assert a.otif_rate == pytest.approx(1 / 4)    # only L1
    assert a.on_time_rate == pytest.approx(3 / 4)  # L1, L2, L6
    assert a.in_full_rate == pytest.approx(2 / 4)  # L1, L2
    assert a.completed_lines == 2                 # lead time only on completed lines
    assert a.overdue_lines == 1 and a.cancelled_lines == 1
    assert a.spend == pytest.approx(5 * 10 * 2.0)  # 6 lines, cancelled L3 excluded from spend


def test_quality_is_quantity_based(facts):
    perf = delivery.supplier_performance(facts.reset_index()).set_index("supplier_id")
    b = perf.loc["B"]
    assert b.reject_rate == pytest.approx(3 / 20)
    assert b.ppv_pct == pytest.approx(0.10)
    assert b.otif_rate == 0 and b.in_full_rate == 1


def test_grace_days_change_on_time(mini):
    f = delivery.line_facts(mini, MINI_AS_OF, grace_days=2).set_index("po_line_id")
    assert f.loc["L7", "otif"]  # 2 days late is inside a 2-day grace period


def test_full_dataset_rates_match_counts(results):
    f = results.facts
    due = f[f["due"]]
    assert results.syn_kpis["due_lines"] == len(due)
    assert results.syn_kpis["otif_rate"] == pytest.approx(due["otif"].sum() / len(due))
    assert not f.loc[~f["due"], ["on_time", "in_full", "otif"]].any().any()
