"""Build the City of Austin analytical model (dimensions + facts) from validated lines.

Grain
-----
fact_po_line     one row per validated purchase-order line (the only fact that carries spend)
fact_po_header   one row per purchase order, aggregated from lines (never re-joined to lines for spend)
dim_vendor       one row per pseudonymous vendor ID; business name only if on the reviewed list
dim_category     one row per NIGP 3-digit class with a dataset-derived label and analyst-defined family

Every join below is many-to-one onto a dimension with a unique key, and `build_model`
asserts that row counts and spend totals are unchanged after joining, so spend cannot be
double counted.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .config import Settings


@dataclass
class AustinModel:
    lines: pd.DataFrame
    headers: pd.DataFrame
    vendors: pd.DataFrame
    categories: pd.DataFrame


def _title(text: str) -> str:
    small = {"and", "or", "of", "for", "the", "to", "in", "a", "with"}
    words = text.lower().split()
    return " ".join(w if (i and w in small) else w.capitalize() for i, w in enumerate(words))


def build_vendors(lines: pd.DataFrame, settings: Settings) -> pd.DataFrame:
    """One row per pseudonymous vendor ID. Business names come only from the reviewed list
    (config/reviewed_vendor_names.csv); every other vendor is shown by its pseudonymous ID."""
    from .ingest import reviewed_vendor_names

    names = reviewed_vendor_names(settings).set_index("vendor_id")["vendor_name"]
    agg = lines.groupby("vendor_code").agg(
        first_award_date=("award_date", "min"),
        last_award_date=("award_date", "max"),
        vendor_country=("vendor_country", "last"),
    ).reset_index()
    agg["name_published"] = agg["vendor_code"].isin(names.index)
    agg["vendor_name"] = agg["vendor_code"].map(names).fillna("Vendor " + agg["vendor_code"])
    return agg[["vendor_code", "vendor_name", "name_published", "vendor_country", "first_award_date", "last_award_date"]]


def build_categories(lines: pd.DataFrame, settings: Settings) -> pd.DataFrame:
    from .ingest import class_labels_path

    families = settings.category_families()
    src = pd.read_csv(class_labels_path(settings), dtype=str).set_index("nigp_class")
    rows = []
    for cls in sorted(lines["nigp_class"].unique()):
        label, source = (_title(src.at[cls, "source_label"]), src.at[cls, "label_source"]) if cls in src.index else ("Unlabelled class", "none")
        if cls == "000":
            label, source = "Unclassified / default fixed asset code", "source code 000"
        rows.append({
            "nigp_class": cls,
            "class_label": f"{cls} {label}"[:70],
            "label_source": source,
            "spend_family": families.get(cls, "Other goods"),
        })
    return pd.DataFrame(rows)


def build_headers(lines: pd.DataFrame) -> pd.DataFrame:
    check = lines.groupby("purchase_order").agg(v=("vendor_code", "nunique"), d=("award_date", "nunique"))
    if (check["v"] > 1).any() or (check["d"] > 1).any():
        raise ValueError("A purchase order maps to more than one vendor or award date; header grain is invalid")
    return lines.groupby("purchase_order", as_index=False).agg(
        vendor_code=("vendor_code", "first"),
        award_date=("award_date", "first"),
        fiscal_year=("fiscal_year", "first"),
        in_focus_window=("in_focus_window", "first"),
        po_type=("po_type", "first"),
        line_count=("line_id", "size"),
        po_amount=("line_amount", "sum"),
        any_master_agreement=("has_master_agreement", "max"),
    )


def build_model(lines: pd.DataFrame, settings: Settings) -> AustinModel:
    vendors = build_vendors(lines, settings)
    categories = build_categories(lines, settings)
    assert vendors["vendor_code"].is_unique and categories["nigp_class"].is_unique

    enriched = lines.merge(vendors[["vendor_code", "vendor_name"]], on="vendor_code", how="left", validate="many_to_one")
    enriched = enriched.merge(categories[["nigp_class", "class_label", "spend_family"]], on="nigp_class", how="left", validate="many_to_one")
    if len(enriched) != len(lines) or abs(enriched["line_amount"].sum() - lines["line_amount"].sum()) > 0.005:
        raise AssertionError("Dimension joins changed the line count or spend total")

    headers = build_headers(enriched)
    return AustinModel(lines=enriched, headers=headers, vendors=vendors, categories=categories)
