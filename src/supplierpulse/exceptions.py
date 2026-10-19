"""Procurement exception register.

Every exception has an ID prefix, a fixed definition and a threshold taken from config, so any
flag can be re-derived by hand from the published tables. Observed (City of Austin) and
synthetic exceptions are kept in one register but always carry their `data_origin`.
"""

from __future__ import annotations

import pandas as pd

from .config import Settings

OBSERVED = "Observed - City of Austin"
SYNTHETIC = "Synthetic demonstration"

DEFINITIONS = {
    "R1": ("Single-vendor concentration", OBSERVED,
           "NIGP class with focus-window spend >= ${min_category_spend:,.0f} where one vendor holds >= {single_vendor_share:.0%} of spend"),
    "R2": ("Highly concentrated category", OBSERVED,
           "NIGP class with spend >= ${min_category_spend:,.0f} and vendor HHI >= {hhi_highly_concentrated:,} (not already R1)"),
    "R3": ("Vendor share of total spend", OBSERVED,
           "Vendor holding >= {vendor_share_of_total:.0%} of all focus-window spend"),
    "R4": ("Recurring purchasing outside master agreements", OBSERVED,
           "NIGP class with >= {min_standalone_orders} standalone orders (contract- or PO-type, no master agreement referenced) "
           "totalling >= ${min_spend_without_agreement:,.0f} in the focus window"),
    "R5": ("Purchase price above item-year baseline", OBSERVED,
           "Comparable item-year with lines priced >= {above_baseline_ratio}x the item-year median unit price"),
    "R6": ("Unusual year-over-year price increase", OBSERVED,
           "Comparable item whose median unit price rose >= 25% from one fiscal year to the next"),
    "S1": ("Chronically late supplier", SYNTHETIC,
           "OTIF < {chronic_late_otif:.0%} with >= {min_lines_for_rate_flags} due lines"),
    "S2": ("Deteriorating delivery performance", SYNTHETIC,
           "OTIF fell >= {deterioration_points:.0%} points from the prior 12 months to the last 12 months (>= {min_lines_for_rate_flags} due lines in each)"),
    "S3": ("Unstable lead times", SYNTHETIC,
           "Lead-time standard deviation >= {unstable_leadtime_sd} days with >= {min_completed_for_variability} completed lines"),
    "S4": ("Recurring incomplete deliveries", SYNTHETIC,
           "In-full rate < {incomplete_in_full_rate:.0%} with >= {min_lines_for_rate_flags} due lines"),
    "S5": ("Quality rejections", SYNTHETIC,
           "Rejected / received quantity >= {quality_reject_rate:.0%} with >= {min_lines_for_rate_flags} due lines"),
    "S6": ("Paid price above contract (PPV)", SYNTHETIC,
           "Spend-weighted paid price >= {ppv_flag_ratio:.0%} above contracted standard price"),
    "S7": ("Overdue open PO line", SYNTHETIC,
           "Open (not cancelled, not short-closed, not fully received) line past its promised date at the as-of date"),
    "S8": ("Supplier dependency", SYNTHETIC,
           "Sole supplier in a category, or >= {high_dependency_category_share:.0%} of a category's spend, or >= {high_dependency_total_share:.0%} of total spend"),
}

COLUMNS = ["exception_id", "rule", "exception_type", "data_origin", "entity_type", "entity_id", "entity_name",
           "metric", "value", "threshold", "exposure_usd", "detail"]


def definitions_table(settings: Settings) -> pd.DataFrame:
    params = {**settings.concentration, **settings.price, **settings.exceptions}
    return pd.DataFrame([
        {"rule": k, "exception_type": v[0], "data_origin": v[1], "definition": v[2].format(**params)}
        for k, v in DEFINITIONS.items()
    ])


def _row(rule, entity_type, entity_id, entity_name, metric, value, threshold, exposure, detail=""):
    return {"rule": rule, "exception_type": DEFINITIONS[rule][0], "data_origin": DEFINITIONS[rule][1],
            "entity_type": entity_type, "entity_id": entity_id, "entity_name": entity_name, "metric": metric,
            "value": value, "threshold": threshold, "exposure_usd": exposure, "detail": detail}


def observed_exceptions(cat_conc: pd.DataFrame, vendors: pd.DataFrame, price_res, settings: Settings) -> list[dict]:
    c = settings.concentration
    p = settings.price
    rows = []
    big = cat_conc[cat_conc["spend"] >= c["min_category_spend"]]
    r1 = big[big["top_vendor_share"] >= c["single_vendor_share"]]
    for r in r1.itertuples():
        recurring = r.top_vendor_orders >= c["recurring_min_orders"] and r.top_vendor_fiscal_years >= c["recurring_min_fiscal_years"]
        pattern = "recurring" if recurring else "few large orders"
        rows.append(_row("R1", "Category", r.nigp_class, r.class_label, "Top vendor share", r.top_vendor_share,
                         c["single_vendor_share"], r.spend,
                         f"Top vendor: {r.top_vendor_name}; {r.top_vendor_orders} order{'s' if r.top_vendor_orders != 1 else ''} over "
                         f"{r.top_vendor_fiscal_years} FY ({pattern}); "
                         f"{r.vendor_count} vendors in class"))
    r2 = big[(big["hhi"] >= c["hhi_highly_concentrated"]) & (big["top_vendor_share"] < c["single_vendor_share"])]
    for r in r2.itertuples():
        rows.append(_row("R2", "Category", r.nigp_class, r.class_label, "Vendor HHI", r.hhi, c["hhi_highly_concentrated"],
                         r.spend, f"Top vendor: {r.top_vendor_name} ({r.top_vendor_share:.0%}); {r.vendor_count} vendors"))
    for r in vendors[vendors["share"] >= c["vendor_share_of_total"]].itertuples():
        rows.append(_row("R3", "Vendor", r.vendor_code, r.vendor_name, "Share of total spend", r.share,
                         c["vendor_share_of_total"], r.spend, f"{r.categories} NIGP classes; {r.po_count:,} POs"))
    r4 = cat_conc[(cat_conc["spend_without_agreement"] >= c["min_spend_without_agreement"])
                  & (cat_conc["standalone_orders"] >= c["min_standalone_orders"])]
    for r in r4.itertuples():
        rows.append(_row("R4", "Category", r.nigp_class, r.class_label, "Standalone orders",
                         r.standalone_orders, c["min_standalone_orders"], r.spend_without_agreement,
                         f"{r.standalone_orders} standalone orders; {1 - r.agreement_share:.0%} of class spend outside master agreements"))
    iy = price_res.item_years
    for r in iy[iy["flagged_lines"] > 0].itertuples():
        rows.append(_row("R5", "Item-year", f"{r.commodity_code}|{r.uom}|FY{r.fiscal_year}", r.item_description[:90],
                         "Max price / item-year median", r.max_price / r.baseline_price, p["above_baseline_ratio"],
                         r.excess_vs_baseline, f"{r.flagged_lines} of {r.lines} lines flagged; {r.vendors} vendor(s); median ${r.baseline_price:,.2f}/{r.uom}"))
    yoy = price_res.yoy
    for r in yoy[yoy["pct_change"] >= 0.25].itertuples():
        rows.append(_row("R6", "Item", r.item_key.split(" | ")[0] + "|" + r.uom, r.item_description[:90],
                         f"Median price change FY{r.prior_fiscal_year}->FY{r.fiscal_year}", r.pct_change, 0.25,
                         r.spend, f"${r.prior_baseline:,.2f} -> ${r.baseline_price:,.2f} per {r.uom}"))
    return rows


def synthetic_exceptions(scorecard: pd.DataFrame, facts: pd.DataFrame, suppliers: pd.DataFrame, settings: Settings) -> list[dict]:
    e = settings.exceptions
    names = suppliers.set_index("supplier_id")["supplier_name"]
    rows = []
    for r in scorecard.itertuples():
        name = names[r.supplier_id]
        enough = r.due_lines >= e["min_lines_for_rate_flags"]
        if enough and r.otif_rate < e["chronic_late_otif"]:
            rows.append(_row("S1", "Supplier", r.supplier_id, name, "OTIF rate", r.otif_rate, e["chronic_late_otif"], r.spend,
                             f"{r.due_lines} due lines; avg {r.avg_days_late_when_late:.1f} days late when late"))
        if (r.due_lines_prior_12m >= e["min_lines_for_rate_flags"] and r.due_lines_last_12m >= e["min_lines_for_rate_flags"]
                and r.otif_change <= -e["deterioration_points"]):
            rows.append(_row("S2", "Supplier", r.supplier_id, name, "OTIF change (pts)", r.otif_change, -e["deterioration_points"],
                             r.spend, f"OTIF {r.otif_prior_12m:.0%} -> {r.otif_last_12m:.0%}"))
        if r.completed_lines >= e["min_completed_for_variability"] and r.lead_time_sd >= e["unstable_leadtime_sd"]:
            rows.append(_row("S3", "Supplier", r.supplier_id, name, "Lead-time SD (days)", r.lead_time_sd, e["unstable_leadtime_sd"],
                             r.spend, f"Average lead time {r.avg_lead_time:.1f} days; P90 {r.lead_time_p90:.0f} days"))
        if enough and r.in_full_rate < e["incomplete_in_full_rate"]:
            rows.append(_row("S4", "Supplier", r.supplier_id, name, "In-full rate", r.in_full_rate, e["incomplete_in_full_rate"],
                             r.spend, f"{r.short_closed_lines} lines closed short"))
        if enough and r.reject_rate >= e["quality_reject_rate"]:
            rows.append(_row("S5", "Supplier", r.supplier_id, name, "Reject rate", r.reject_rate, e["quality_reject_rate"],
                             r.spend, f"{r.rejected_qty:,} of {r.received_qty:,} units rejected"))
        if r.ppv_pct >= e["ppv_flag_ratio"]:
            rows.append(_row("S6", "Supplier", r.supplier_id, name, "PPV vs contract", r.ppv_pct, e["ppv_flag_ratio"],
                             r.ppv_amount, f"${r.ppv_amount:,.0f} paid above contract price"))
        if r.dependency_risk == "High":
            why = "sole supplier in category" if r.suppliers_in_category == 1 else (
                f"{r.max_category_share:.0%} of {r.main_category_id} spend, {r.share_of_total_spend:.0%} of total")
            rows.append(_row("S8", "Supplier", r.supplier_id, name, "Max category share", r.max_category_share,
                             e["high_dependency_category_share"], r.spend, why))
    od = facts[facts["overdue"]].sort_values(["days_late", "po_line_id"], ascending=[False, True])
    for r in od.itertuples():
        rows.append(_row("S7", "PO line", r.po_line_id, names[r.supplier_id], "Days past promised date", r.days_late, 0,
                         r.open_value, f"{r.item_id}; {r.open_qty} of {r.ordered_qty} units outstanding; promised {r.promised_date:%Y-%m-%d}"))
    return rows


def build_register(observed: list[dict], synthetic: list[dict]) -> pd.DataFrame:
    reg = pd.DataFrame(observed + synthetic)
    reg = reg.sort_values(["rule", "exposure_usd", "entity_id"], ascending=[True, False, True]).reset_index(drop=True)
    reg["exception_id"] = reg["rule"] + "-" + (reg.groupby("rule").cumcount() + 1).astype(str).str.zfill(3)
    return reg[COLUMNS]
