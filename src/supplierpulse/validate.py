"""Validate and standardise City of Austin purchase-order lines from the public snapshot.

Rules (each is documented in docs/methodology.md and counted in the data-quality audit):

V1  Required fields (PO number, vendor ID, award date, line amount, commodity) must be present.
V2  Award date must parse as MM/DD/YYYY and fall on or before the source data build date.
V3  Line amount must be numeric and greater than zero.
V4  Quantity and unit price must be numeric and non-negative.
V5  Line type:
      unit_priced   quantity > 0, unit price > 0, unit of measure present and quantity x unit price
                    reconciles to the line amount (within 0.5% or $0.01)
      amount_only   quantity = 0 and unit price = 0 (an amount-based line; valid spend, no price)
      inconsistent  anything else (valid spend, excluded from all price comparisons)
V6  Exact duplicate rows (all 21 source columns identical, detected before any column was
    dropped) are flagged, not removed: the source has no line number, so two identical lines on
    one PO cannot be proven to be an error. Their value and effect are reported in the audit.
V7  PO numbers with a letter suffix (e.g. ...417A) whose base number also exists are flagged as
    possible follow-on/revision orders. Each carries its own line amounts, so both are retained.
V8  Currency is not stated in the source; all amounts are City of Austin purchase orders and are
    treated as USD (an explicit assumption).
V9  Price comparisons only use lines whose item text is on the human-reviewed product
    specification list (config/reviewed_item_texts.csv).

Rows failing V1-V4 are excluded and logged with a reason; nothing is silently dropped.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .config import Settings
from .ingest import SNAPSHOT_COLUMNS

REQUIRED = ["PURCHASE_ORDER", "VENDOR_ID", "AWARD_DATE", "ITM_TOT_AM", "COMMODITY"]


@dataclass
class CleanResult:
    lines: pd.DataFrame
    excluded: pd.DataFrame
    audit: dict = field(default_factory=dict)


def fiscal_year(dates: pd.Series, start_month: int = 10) -> pd.Series:
    return (dates.dt.year + (dates.dt.month >= start_month).astype(int)).astype("int64")


def normalise_text(s: pd.Series) -> pd.Series:
    return s.fillna("").astype(str).str.upper().str.replace(r"\s+", " ", regex=True).str.strip()


def _bool(s: pd.Series) -> pd.Series:
    if s.dtype == bool:
        return s
    return s.astype(str).str.lower().isin(["true", "1", "yes"])


def clean_austin(raw: pd.DataFrame, settings: Settings, item_labels: dict[str, str] | None = None) -> CleanResult:
    missing_cols = [c for c in SNAPSHOT_COLUMNS if c not in raw.columns]
    if missing_cols:
        raise ValueError(f"Schema validation failed; missing columns: {missing_cols}")
    if item_labels is None:
        from .ingest import reviewed_item_texts

        rv = reviewed_item_texts(settings)
        item_labels = dict(zip(rv["text_sha256"], rv["public_label"]))

    df = raw.copy()
    text_cols = [c for c in df.columns if c not in ("SOURCE_ROW", "HAS_MASTER_AGREEMENT", "RAW_EXACT_DUPLICATE")]
    for col in text_cols:
        df[col] = df[col].fillna("").astype(str).str.strip()

    reason = pd.Series("", index=df.index, dtype=object)

    def mark(mask: pd.Series, why: str) -> None:
        reason.loc[mask & (reason == "")] = why

    mark(df[REQUIRED].eq("").any(axis=1), "V1_missing_required_field")

    award = pd.to_datetime(df["AWARD_DATE"], format="%m/%d/%Y", errors="coerce")
    build = pd.to_datetime(df["DATA_BUILD_DATE"], format="%m/%d/%Y", errors="coerce")
    mark(award.isna(), "V2_invalid_award_date")
    mark(award.notna() & build.notna() & (award > build), "V2_award_after_build_date")

    amount = pd.to_numeric(df["ITM_TOT_AM"].str.replace(",", "", regex=False), errors="coerce")
    qty = pd.to_numeric(df["QUANTITY"].replace("", "0").str.replace(",", "", regex=False), errors="coerce")
    unit_price = pd.to_numeric(df["UNIT_PRICE"].replace("", "0").str.replace(",", "", regex=False), errors="coerce")
    mark(amount.isna() | (amount <= 0), "V3_non_positive_or_invalid_amount")
    mark(qty.isna() | unit_price.isna(), "V4_invalid_quantity_or_price")
    mark((qty < 0) | (unit_price < 0), "V4_negative_quantity_or_price")

    excluded_mask = reason != ""
    excluded = pd.DataFrame({
        "source_row": df.loc[excluded_mask, "SOURCE_ROW"].values,
        "reason": reason[excluded_mask].values,
        "purchase_order": df.loc[excluded_mask, "PURCHASE_ORDER"].values,
        "line_amount": amount[excluded_mask].values,
    })

    keep = ~excluded_mask
    d = df.loc[keep].copy()
    d["award_date"] = award[keep]
    d["line_amount"] = amount[keep].round(2)
    d["quantity"] = qty[keep]
    d["unit_price"] = unit_price[keep]
    d["uom"] = normalise_text(d["UNIT_OF_MEASURE"])

    reconciles = (d["quantity"] * d["unit_price"] - d["line_amount"]).abs() <= np.maximum(0.01, 0.005 * d["line_amount"])
    unit_priced = (d["quantity"] > 0) & (d["unit_price"] > 0) & (d["uom"] != "") & reconciles
    amount_only = (d["quantity"] == 0) & (d["unit_price"] == 0)
    d["line_type"] = np.select([unit_priced, amount_only], ["unit_priced", "amount_only"], "inconsistent")

    d["possible_duplicate"] = _bool(d["RAW_EXACT_DUPLICATE"])
    po = d["PURCHASE_ORDER"]
    base = po.str.replace(r"[A-Z]+$", "", regex=True)
    d["po_suffix_revision"] = (base != po) & base.isin(set(po))

    a = settings.analysis
    d["fiscal_year"] = fiscal_year(d["award_date"], a["fiscal_year_start_month"])
    d["in_focus_window"] = d["fiscal_year"].between(a["focus_fy_start"], a["focus_fy_end"])
    d["commodity_code"] = d["COMMODITY"]
    d["nigp_class"] = d["COMMODITY"].str[:3]
    d["has_master_agreement"] = _bool(d["HAS_MASTER_AGREEMENT"])
    d["po_type"] = d["PURCHASE_ORDER"].str[:2]
    d["item_text_key"] = d["ITEM_TEXT_KEY"]
    d["item_specific"] = d["item_text_key"].isin(item_labels.keys())
    d["item_description"] = d["item_text_key"].map(item_labels).fillna("")
    d["currency"] = "USD"

    lines = d.rename(columns={
        "SOURCE_ROW": "source_row", "PURCHASE_ORDER": "purchase_order", "VENDOR_ID": "vendor_code",
        "VENDOR_COUNTRY": "vendor_country",
    })[[
        "source_row", "purchase_order", "po_type", "po_suffix_revision", "award_date", "fiscal_year",
        "in_focus_window", "vendor_code", "vendor_country", "commodity_code", "nigp_class",
        "item_text_key", "item_description", "item_specific", "uom",
        "quantity", "unit_price", "line_amount", "currency", "line_type", "has_master_agreement", "possible_duplicate",
    ]].reset_index(drop=True)
    lines.insert(0, "line_id", np.arange(1, len(lines) + 1, dtype="int64"))

    raw_amount_total = float(pd.to_numeric(df["ITM_TOT_AM"].str.replace(",", "", regex=False), errors="coerce").fillna(0).sum())
    dup = lines["possible_duplicate"]
    audit = {
        "raw_rows": int(len(df)),
        "raw_amount_total": round(raw_amount_total, 2),
        "excluded_rows": int(excluded_mask.sum()),
        "excluded_by_reason": excluded["reason"].value_counts().to_dict(),
        "excluded_amount": round(float(excluded["line_amount"].fillna(0).sum()), 2),
        "clean_rows": int(len(lines)),
        "clean_amount_total": round(float(lines["line_amount"].sum()), 2),
        "line_type_counts": lines["line_type"].value_counts().to_dict(),
        "possible_duplicate_rows": int(dup.sum()),
        "possible_duplicate_amount": round(float(lines.loc[dup, "line_amount"].sum()), 2),
        "possible_duplicate_rows_focus": int((dup & lines["in_focus_window"]).sum()),
        "possible_duplicate_amount_focus": round(float(lines.loc[dup & lines["in_focus_window"], "line_amount"].sum()), 2),
        "po_suffix_revision_rows": int(lines["po_suffix_revision"].sum()),
        "po_suffix_revision_amount": round(float(lines.loc[lines["po_suffix_revision"], "line_amount"].sum()), 2),
        "award_date_min": lines["award_date"].min().strftime("%Y-%m-%d"),
        "award_date_max": lines["award_date"].max().strftime("%Y-%m-%d"),
        "source_build_dates": sorted(df["DATA_BUILD_DATE"].unique().tolist()),
        "missing_uom_rows": int((lines["uom"] == "").sum()),
        "missing_master_agreement_rows": int((~lines["has_master_agreement"]).sum()),
        "reviewed_item_text_rows": int(lines["item_specific"].sum()),
        "non_us_vendor_rows": int((~lines["vendor_country"].isin(["US", ""])).sum()),
        "blank_country_rows": int((lines["vendor_country"] == "").sum()),
    }
    return CleanResult(lines=lines, excluded=excluded, audit=audit)
