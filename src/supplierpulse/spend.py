"""Part A: purchasing spend and concentration metrics on City of Austin data (observed).

"Spend" here is the awarded purchase-order line value (a commitment at award), not invoiced
or paid amounts. Unless a function says otherwise it is restricted to the focus window
(complete fiscal years set in config: FY2022-FY2026).
"""

from __future__ import annotations

import pandas as pd

from .config import Settings


def hhi(shares: pd.Series) -> float:
    """Herfindahl-Hirschman Index on the 0-10,000 scale from fractional shares."""
    shares = shares[shares > 0]
    return float(((shares * 100) ** 2).sum())


def focus(lines: pd.DataFrame) -> pd.DataFrame:
    f = lines[lines["in_focus_window"]].copy()
    f["agreement_amount"] = f["line_amount"].where(f["has_master_agreement"], 0.0)
    return f


def kpis(lines: pd.DataFrame, headers: pd.DataFrame) -> dict:
    f = focus(lines)
    h = headers[headers["in_focus_window"]]
    total = float(f["line_amount"].sum())
    vend = f.groupby("vendor_code")["line_amount"].sum().sort_values(ascending=False)
    shares = vend / total
    cum = shares.cumsum()
    return {
        "total_spend": total,
        "po_count": int(h["purchase_order"].nunique()),
        "line_count": int(len(f)),
        "active_vendors": int(f["vendor_code"].nunique()),
        "avg_po_value": total / len(h),
        "median_po_value": float(h["po_amount"].median()),
        "master_agreement_share": float(f.loc[f["has_master_agreement"], "line_amount"].sum() / total),
        "top10_vendor_share": float(shares.head(10).sum()),
        "vendor_hhi": hhi(shares),
        "vendors_for_80pct": int((cum < 0.80).sum() + 1),
        "categories_with_spend": int(f["nigp_class"].nunique()),
    }


def spend_by_fiscal_year(lines: pd.DataFrame, settings: Settings) -> pd.DataFrame:
    a = settings.analysis
    hist = lines[lines["fiscal_year"].between(a["history_fy_start"], a["focus_fy_end"])]
    out = hist.groupby("fiscal_year").agg(
        spend=("line_amount", "sum"),
        po_count=("purchase_order", "nunique"),
        line_count=("line_id", "size"),
        active_vendors=("vendor_code", "nunique"),
    ).reset_index()
    out["in_focus_window"] = out["fiscal_year"].between(a["focus_fy_start"], a["focus_fy_end"])
    return out


def vendor_spend(lines: pd.DataFrame) -> pd.DataFrame:
    f = focus(lines)
    total = f["line_amount"].sum()
    v = f.groupby(["vendor_code", "vendor_name"]).agg(
        spend=("line_amount", "sum"),
        po_count=("purchase_order", "nunique"),
        line_count=("line_id", "size"),
        categories=("nigp_class", "nunique"),
        agreement_spend=("agreement_amount", "sum"),
    ).reset_index()
    # Deterministic ordering: spend descending, vendor code ascending for exact ties
    v = v.sort_values(["spend", "vendor_code"], ascending=[False, True]).reset_index(drop=True)
    v["rank"] = range(1, len(v) + 1)
    v["share"] = v["spend"] / total
    v["cumulative_share"] = v["share"].cumsum()
    v["avg_po_value"] = v["spend"] / v["po_count"]
    v["agreement_share"] = v["agreement_spend"] / v["spend"]
    # Pareto class by the cumulative share *before* the vendor: A until 80% is reached, B until 95%, then C
    v["pareto_class"] = pd.cut(v["cumulative_share"].shift(fill_value=0), [-1, 0.80, 0.95, 2], labels=["A", "B", "C"], right=False).astype(str)
    return v


def category_concentration(lines: pd.DataFrame) -> pd.DataFrame:
    """One row per NIGP class: spend, vendor count, top-vendor share, HHI, agreement coverage."""
    f = focus(lines)
    total = f["line_amount"].sum()
    cv = f.groupby(["nigp_class", "vendor_code", "vendor_name"])["line_amount"].sum().reset_index()
    rows = []
    for cls, grp in cv.groupby("nigp_class"):
        cls_spend = grp["line_amount"].sum()
        grp = grp.sort_values(["line_amount", "vendor_code"], ascending=[False, True])
        shares = grp["line_amount"] / cls_spend
        top = grp.iloc[0]
        top_lines = f[(f["nigp_class"] == cls) & (f["vendor_code"] == top["vendor_code"])]
        rows.append({
            "nigp_class": cls,
            "top_vendor_orders": int(top_lines["purchase_order"].nunique()),
            "top_vendor_fiscal_years": int(top_lines["fiscal_year"].nunique()),
            "spend": cls_spend,
            "vendor_count": len(grp),
            "top_vendor_code": top["vendor_code"],
            "top_vendor_name": top["vendor_name"],
            "top_vendor_share": float(shares.iloc[0]),
            "hhi": hhi(shares),
        })
    out = pd.DataFrame(rows)
    cat_info = f.groupby("nigp_class").agg(
        class_label=("class_label", "first"),
        spend_family=("spend_family", "first"),
        line_count=("line_id", "size"),
        po_count=("purchase_order", "nunique"),
        agreement_spend=("agreement_amount", "sum"),
    ).reset_index()
    out = out.merge(cat_info, on="nigp_class", validate="one_to_one")
    standalone = f[~f["has_master_agreement"]].groupby("nigp_class")["purchase_order"].nunique()
    out["standalone_orders"] = out["nigp_class"].map(standalone).fillna(0).astype("int64")
    out["share_of_total"] = out["spend"] / total
    out["spend_without_agreement"] = out["spend"] - out.pop("agreement_spend")
    out["agreement_share"] = 1 - out["spend_without_agreement"] / out["spend"]
    return out.sort_values(["spend", "nigp_class"], ascending=[False, True]).reset_index(drop=True)


def family_spend(lines: pd.DataFrame) -> pd.DataFrame:
    f = focus(lines)
    total = f["line_amount"].sum()
    out = f.groupby("spend_family").agg(
        spend=("line_amount", "sum"),
        vendor_count=("vendor_code", "nunique"),
        po_count=("purchase_order", "nunique"),
        classes=("nigp_class", "nunique"),
    ).reset_index()
    out["share"] = out["spend"] / total
    return out.sort_values("spend", ascending=False).reset_index(drop=True)


def family_trend(lines: pd.DataFrame) -> pd.DataFrame:
    f = focus(lines)
    return f.pivot_table(index="spend_family", columns="fiscal_year", values="line_amount", aggfunc="sum", fill_value=0.0)
