"""Observed (City of Austin) pipeline: validation, reconciliation, joins, concentration and prices."""

import numpy as np
import pandas as pd
import pytest

from supplierpulse import price, spend, transform, validate
from supplierpulse.ingest import SNAPSHOT_COLUMNS


def raw_rows(rows):
    base = {c: "" for c in SNAPSHOT_COLUMNS}
    out = []
    for i, r in enumerate(rows, start=1):
        rec = dict(base, SOURCE_ROW=i, COMMODITY="28500000001", PURCHASE_ORDER=f"DO{i:03d}", AWARD_DATE="01/15/2024",
                   VENDOR_ID="V0000000001", VENDOR_COUNTRY="US", ITM_TOT_AM="100", QUANTITY="10", UNIT_PRICE="10",
                   UNIT_OF_MEASURE="EA", DATA_BUILD_DATE="10/05/2026", HAS_MASTER_AGREEMENT=True, ITEM_TEXT_KEY="",
                   RAW_EXACT_DUPLICATE=False)
        rec.update(r)
        out.append(rec)
    return pd.DataFrame(out)


def test_schema_validation_rejects_missing_column(settings):
    with pytest.raises(ValueError, match="Schema validation failed"):
        validate.clean_austin(raw_rows([{}]).drop(columns=["VENDOR_ID"]), settings)


def test_invalid_rows_excluded_with_reason_and_totals_reconcile(settings):
    df = raw_rows([{}, {"AWARD_DATE": "2024-13-01"}, {"ITM_TOT_AM": "0"}, {"ITM_TOT_AM": "-5"}, {"QUANTITY": "-1"},
                   {"VENDOR_ID": ""}, {"AWARD_DATE": "12/01/2026"}])
    res = validate.clean_austin(df, settings)
    reasons = res.excluded.set_index("source_row")["reason"]
    assert len(res.lines) == 1
    assert reasons[2] == "V2_invalid_award_date" and reasons[3].startswith("V3") and reasons[4].startswith("V3")
    assert reasons[5].startswith("V4") and reasons[6].startswith("V1") and reasons[7] == "V2_award_after_build_date"
    a = res.audit
    assert a["clean_amount_total"] + a["excluded_amount"] == pytest.approx(a["raw_amount_total"])


def test_line_types_and_duplicates(settings):
    df = raw_rows([{}, {"QUANTITY": "0", "UNIT_PRICE": "0", "UNIT_OF_MEASURE": ""}, {"QUANTITY": "3", "UNIT_PRICE": "10"},
                   {"PURCHASE_ORDER": "DO001", "RAW_EXACT_DUPLICATE": True}])  # flagged upstream on the full private row
    res = validate.clean_austin(df, settings)
    lt = res.lines.set_index("source_row")["line_type"]
    assert lt[1] == "unit_priced" and lt[2] == "amount_only" and lt[3] == "inconsistent"
    dup = res.lines.set_index("source_row")["possible_duplicate"]
    assert not dup[1] and dup[4]                    # flagged, not removed
    assert res.lines["line_amount"].sum() == pytest.approx(400)


def test_fiscal_year_boundaries(settings):
    res = validate.clean_austin(raw_rows([{"AWARD_DATE": "09/30/2025"}, {"AWARD_DATE": "10/01/2025"}]), settings)
    assert res.lines["fiscal_year"].tolist() == [2025, 2026]


def test_full_dataset_reconciles_and_joins_do_not_double_count(results):
    a = results.clean.audit
    assert a["clean_rows"] + a["excluded_rows"] == a["raw_rows"]
    assert a["clean_amount_total"] + a["excluded_amount"] == pytest.approx(a["raw_amount_total"], abs=0.01)
    m = results.model
    assert len(m.lines) == a["clean_rows"]
    assert m.lines["line_amount"].sum() == pytest.approx(a["clean_amount_total"], abs=0.01)
    assert m.headers["po_amount"].sum() == pytest.approx(m.lines["line_amount"].sum(), abs=0.01)
    focus = m.lines[m.lines["in_focus_window"]]
    for table in (results.vendors, results.categories, results.families):
        assert table["spend"].sum() == pytest.approx(focus["line_amount"].sum(), abs=0.01)


def test_hhi_known_values():
    assert spend.hhi(pd.Series([1.0])) == pytest.approx(10000)
    assert spend.hhi(pd.Series([0.5, 0.5])) == pytest.approx(5000)
    assert spend.hhi(pd.Series([0.25] * 4)) == pytest.approx(2500)


def _lines(rows):
    df = pd.DataFrame(rows)
    df["in_focus_window"] = True
    df["line_id"] = range(1, len(df) + 1)
    for c, v in {"purchase_order": None, "has_master_agreement": True, "class_label": "L", "spend_family": "F",
                 "fiscal_year": 2024, "vendor_name": None}.items():
        if c not in df:
            df[c] = v
    df["has_master_agreement"] = df["has_master_agreement"].fillna(True).astype(bool)
    df["purchase_order"] = df["purchase_order"].fillna(pd.Series([f"P{i}" for i in df["line_id"]]))
    df["vendor_name"] = df["vendor_name"].fillna(df["vendor_code"])
    return df


def test_category_concentration_and_vendor_shares():
    lines = _lines([
        {"nigp_class": "100", "vendor_code": "A", "line_amount": 90.0},
        {"nigp_class": "100", "vendor_code": "B", "line_amount": 10.0},
        {"nigp_class": "200", "vendor_code": "B", "line_amount": 100.0, "has_master_agreement": False},
    ])
    cc = spend.category_concentration(lines).set_index("nigp_class")
    assert cc.loc["100", "top_vendor_share"] == pytest.approx(0.9)
    assert cc.loc["100", "hhi"] == pytest.approx(90**2 + 10**2)
    assert cc.loc["200", "hhi"] == pytest.approx(10000) and cc.loc["200", "spend_without_agreement"] == 100
    v = spend.vendor_spend(lines).set_index("vendor_code")
    assert v["share"].sum() == pytest.approx(1)
    assert v.loc["B", "share"] == pytest.approx(110 / 200) and v.loc["B", "rank"] == 1


def test_tied_vendor_spend_ranked_deterministically():
    lines = _lines([{"nigp_class": "100", "vendor_code": c, "line_amount": 50.0} for c in ["Z", "A", "M"]])
    v = spend.vendor_spend(lines)
    assert v["vendor_code"].tolist() == ["A", "M", "Z"] and v["rank"].tolist() == [1, 2, 3]


def _price_lines(rows):
    base = dict(in_focus_window=True, line_type="unit_priced", item_specific=True, possible_duplicate=False,
                commodity_code="11111111111", uom="EA", item_description="BOLT", item_text_key="k-bolt", fiscal_year=2024, vendor_code="V",
                vendor_name="V", class_label="L", quantity=1.0)
    df = pd.DataFrame([dict(base, **r) for r in rows])
    df["line_id"] = range(1, len(df) + 1)
    df["line_amount"] = df["unit_price"] * df["quantity"]
    return df


def test_price_comparisons_control_unit_and_specificity(settings):
    rows = [{"unit_price": p} for p in (10, 10, 10, 20)]                        # item-year A: median 10, one line 2x
    rows += [{"unit_price": 100, "uom": "BOX"}] * 4                             # same code, different unit: own group
    rows += [{"unit_price": 999, "item_specific": False}] * 4                   # generic description: excluded
    rows += [{"unit_price": 0, "line_type": "amount_only"}] * 4                 # amount-only: excluded
    rows += [{"unit_price": 10, "item_description": "NUT", "item_text_key": "k-nut"}] * 3  # below minimum lines: excluded
    rows += [{"unit_price": 10, "fiscal_year": 2025}] * 3 + [{"unit_price": 200, "fiscal_year": 2025}]  # 20x -> entry issue
    res = price.analyse_prices(_price_lines(rows), settings)
    iy = res.item_years.set_index(["uom", "fiscal_year"])
    assert set(res.item_years["item_description"]) == {"BOLT"}
    assert len(res.item_years) == 3
    assert iy.loc[("EA", 2024), "baseline_price"] == 10 and iy.loc[("EA", 2024), "flagged_lines"] == 1
    assert iy.loc[("EA", 2024), "excess_vs_baseline"] == pytest.approx(10)
    assert iy.loc[("BOX", 2024), "flagged_lines"] == 0
    assert iy.loc[("EA", 2025), "entry_issue_lines"] == 1 and iy.loc[("EA", 2025), "excess_vs_baseline"] == 0
    assert res.summary["modelled_opportunity_full"] == pytest.approx(10)


def test_year_over_year_only_pairs_consecutive_years():
    iy = pd.DataFrame({"item_key": ["K", "K", "K"], "fiscal_year": [2022, 2023, 2025], "baseline_price": [100.0, 150.0, 300.0],
                       "lines": [5, 5, 5], "item_description": "X", "uom": "EA", "class_label": "L", "spend": 1.0})
    y = price.year_over_year(iy)
    assert len(y) == 1 and y.iloc[0]["pct_change"] == pytest.approx(0.5)


def test_published_price_lines_respect_rules(results, settings):
    pl = results.prices.lines
    assert (pl["line_type"] == "unit_priced").all() and pl["item_specific"].all() and not pl["possible_duplicate"].any()
    assert (pl.groupby(["item_key", "fiscal_year"]).size() >= settings.price["min_lines_per_item_year"]).all()
    assert (pl.groupby(["item_key", "fiscal_year"])["uom"].nunique() == 1).all()


def test_pareto_and_80pct_definition(results):
    v = results.vendors
    k = results.kpis["vendors_for_80pct"]
    assert v["cumulative_share"].iloc[k - 1] >= 0.80 > v["cumulative_share"].iloc[k - 2]
    assert (v["pareto_class"] == "A").sum() == k


def test_category_family_mapping_has_no_duplicates(settings):
    mapping = settings.category_families()
    assert len(mapping) == len(set(mapping))
    assert all(len(k) == 3 and k.isdigit() for k in mapping)


def test_reviewed_item_text_is_the_only_route_into_price_comparison(settings):
    df = raw_rows([{"ITEM_TEXT_KEY": "not-on-the-reviewed-list"}, {"ITEM_TEXT_KEY": ""}])
    res = validate.clean_austin(df, settings, item_labels={"reviewed-key": "BOLT 1/2 IN"})
    assert not res.lines["item_specific"].any() and (res.lines["item_description"] == "").all()
    res = validate.clean_austin(raw_rows([{"ITEM_TEXT_KEY": "reviewed-key"}]), settings, item_labels={"reviewed-key": "BOLT 1/2 IN"})
    assert res.lines["item_specific"].all() and res.lines.loc[0, "item_description"] == "BOLT 1/2 IN"


def test_model_vendor_dimension_unique(results):
    assert results.model.vendors["vendor_code"].is_unique
    assert results.model.categories["nigp_class"].is_unique
    assert not np.any(results.model.lines["vendor_name"].isna())


def test_build_model_rejects_po_with_two_vendors(settings):
    res = validate.clean_austin(raw_rows([{"PURCHASE_ORDER": "DO1"}, {"PURCHASE_ORDER": "DO1", "VENDOR_ID": "V0000000002"}]), settings)
    with pytest.raises(ValueError, match="more than one vendor"):
        transform.build_model(res.lines, settings)
