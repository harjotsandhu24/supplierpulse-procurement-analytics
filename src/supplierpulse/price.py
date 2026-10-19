"""Part A: like-for-like purchase price variance on City of Austin data (observed).

Comparability controls
----------------------
A price is only compared with prices for the *same item*:
  * same commodity code (full code, not just the class),
  * same unit of measure,
  * same normalised item text, and that text must be on the human-reviewed list of genuine
    product specifications (config/reviewed_item_texts.csv); delivery notes, quote/bid
    references, names, service descriptions and vague text are never compared,
  * same fiscal year (so multi-year inflation is not read as price variance),
  * only `unit_priced` lines whose quantity x unit price reconciles to the line amount,
  * possible duplicate rows are excluded,
  * the item-year needs at least `min_lines_per_item_year` purchases to form a baseline.

Baseline = median unit price of the item-year. A line at >= `above_baseline_ratio` x baseline
is flagged. Lines at <= `entry_error_low_ratio` x or >= `entry_error_high_ratio` x baseline are
treated as probable unit or data-entry inconsistencies: reported, but excluded from opportunity.

The "price harmonisation opportunity" is modelled, not realised: it is what the flagged lines
would have cost at the item-year median, and it ignores order size, urgency, delivery terms
and specification differences that the source data cannot show.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import Settings


@dataclass
class PriceResult:
    lines: pd.DataFrame        # comparable lines with baseline and flags
    item_years: pd.DataFrame   # one row per item-year baseline
    vendor_index: pd.DataFrame # spend-weighted price index by vendor
    yoy: pd.DataFrame          # year-over-year change in item baseline price
    summary: dict


def comparable_lines(lines: pd.DataFrame) -> pd.DataFrame:
    c = lines[
        lines["in_focus_window"]
        & (lines["line_type"] == "unit_priced")
        & lines["item_specific"]
        & ~lines["possible_duplicate"]
    ].copy()
    # The key uses the hash of the full reviewed text, so two texts that share a cleaned public
    # label are still treated as different items.
    c["item_key"] = c["commodity_code"] + " | " + c["uom"] + " | " + c["item_text_key"]
    return c


def analyse_prices(lines: pd.DataFrame, settings: Settings) -> PriceResult:
    p = settings.price
    c = comparable_lines(lines)
    grp = c.groupby(["item_key", "fiscal_year"])
    c["item_year_lines"] = grp["unit_price"].transform("size")
    c = c[c["item_year_lines"] >= p["min_lines_per_item_year"]].copy()
    grp = c.groupby(["item_key", "fiscal_year"])
    c["baseline_price"] = grp["unit_price"].transform("median")
    c["price_ratio"] = c["unit_price"] / c["baseline_price"]

    entry_issue = (c["price_ratio"] <= p["entry_error_low_ratio"]) | (c["price_ratio"] >= p["entry_error_high_ratio"])
    above = (c["price_ratio"] >= p["above_baseline_ratio"]) & ~entry_issue
    c["price_flag"] = np.select([entry_issue, above], ["probable_unit_or_entry_issue", "above_baseline"], "within_range")
    c["excess_vs_baseline"] = np.where(above, (c["unit_price"] - c["baseline_price"]) * c["quantity"], 0.0)
    # Order-size control: a line counts in the quantity-controlled figure only if its quantity is within
    # 0.5x-2x of the item-year median quantity (small urgent orders often carry higher unit prices).
    median_qty = grp["quantity"].transform("median")
    c["quantity_comparable"] = c["quantity"].between(0.5 * median_qty, 2 * median_qty)

    item_years = grp.agg(
        commodity_code=("commodity_code", "first"),
        uom=("uom", "first"),
        item_description=("item_description", "first"),
        class_label=("class_label", "first"),
        lines=("line_id", "size"),
        vendors=("vendor_code", "nunique"),
        spend=("line_amount", "sum"),
        baseline_price=("unit_price", "median"),
        min_price=("unit_price", "min"),
        max_price=("unit_price", "max"),
    ).reset_index()
    flags = c.groupby(["item_key", "fiscal_year"]).agg(
        flagged_lines=("price_flag", lambda s: int((s == "above_baseline").sum())),
        entry_issue_lines=("price_flag", lambda s: int((s == "probable_unit_or_entry_issue").sum())),
        excess_vs_baseline=("excess_vs_baseline", "sum"),
    ).reset_index()
    item_years = item_years.merge(flags, on=["item_key", "fiscal_year"], validate="one_to_one")
    item_years["dispersion_ratio"] = item_years["max_price"] / item_years["min_price"]
    item_years = item_years.sort_values(["excess_vs_baseline", "item_key"], ascending=[False, True]).reset_index(drop=True)

    valid = c[c["price_flag"] != "probable_unit_or_entry_issue"].copy()
    valid["baseline_amount"] = valid["baseline_price"] * valid["quantity"]
    vi = valid.groupby(["vendor_code", "vendor_name"]).agg(
        comparable_lines=("line_id", "size"),
        items=("item_key", "nunique"),
        paid_amount=("line_amount", "sum"),
        baseline_amount=("baseline_amount", "sum"),
        flagged_lines=("price_flag", lambda s: int((s == "above_baseline").sum())),
        excess_vs_baseline=("excess_vs_baseline", "sum"),
    ).reset_index()
    vi["price_index"] = vi["paid_amount"] / vi["baseline_amount"]
    vi = vi.sort_values(["excess_vs_baseline", "vendor_code"], ascending=[False, True]).reset_index(drop=True)

    yoy = year_over_year(item_years)

    all_unit_priced = lines[lines["in_focus_window"] & (lines["line_type"] == "unit_priced")]
    focus_total = lines.loc[lines["in_focus_window"], "line_amount"].sum()
    summary = {
        "comparable_lines": int(len(c)),
        "comparable_item_years": int(len(item_years)),
        "comparable_items": int(item_years["item_key"].nunique()),
        "comparable_spend": float(c["line_amount"].sum()),
        "comparable_share_of_unit_priced_spend": float(c["line_amount"].sum() / all_unit_priced["line_amount"].sum()),
        "comparable_share_of_total_spend": float(c["line_amount"].sum() / focus_total),
        "flagged_lines": int((c["price_flag"] == "above_baseline").sum()),
        "flagged_spend": float(c.loc[c["price_flag"] == "above_baseline", "line_amount"].sum()),
        "entry_issue_lines": int((c["price_flag"] == "probable_unit_or_entry_issue").sum()),
        "modelled_opportunity_full": float(c["excess_vs_baseline"].sum()),
        "flagged_lines_quantity_controlled": int(((c["price_flag"] == "above_baseline") & c["quantity_comparable"]).sum()),
        "modelled_opportunity_quantity_controlled": float(c.loc[c["quantity_comparable"], "excess_vs_baseline"].sum()),
        "yoy_item_pairs": int(len(yoy)),
        "yoy_increases_25pct": int((yoy["pct_change"] >= 0.25).sum()),
        "yoy_median_change": float(yoy["pct_change"].median()) if len(yoy) else float("nan"),
    }
    return PriceResult(lines=c, item_years=item_years, vendor_index=vi, yoy=yoy, summary=summary)


def year_over_year(item_years: pd.DataFrame) -> pd.DataFrame:
    """Median-price change for the same item between consecutive fiscal years.

    Only consecutive years where both years meet the minimum-lines rule are paired.
    """
    iy = item_years.sort_values(["item_key", "fiscal_year"])
    prev = iy.groupby("item_key")[["fiscal_year", "baseline_price", "lines"]].shift(1)
    out = iy.assign(prior_fiscal_year=prev["fiscal_year"], prior_baseline=prev["baseline_price"], prior_lines=prev["lines"])
    out = out[out["prior_fiscal_year"] == out["fiscal_year"] - 1].copy()
    out["prior_fiscal_year"] = out["prior_fiscal_year"].astype("int64")
    out["pct_change"] = out["baseline_price"] / out["prior_baseline"] - 1
    cols = ["item_key", "item_description", "uom", "class_label", "prior_fiscal_year", "fiscal_year",
            "prior_baseline", "baseline_price", "pct_change", "prior_lines", "lines", "spend"]
    return out[cols].sort_values(["pct_change", "item_key"], ascending=[False, True]).reset_index(drop=True)
