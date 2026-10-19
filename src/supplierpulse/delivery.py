"""Supplier delivery performance (Part B, synthetic data).

Unit of measurement: the purchase-order LINE. Definitions (see docs/methodology.md):

due line           not cancelled and promised date <= reporting (as-of) date. Only due lines enter
                   delivery-rate denominators; lines not yet due are excluded, never counted as on time.
on time (OT)       at least one receipt on or before promised date + grace days.
in full (IF)       cumulative received quantity at the as-of date >= ordered quantity x (1 - tolerance).
OTIF               cumulative quantity received on or before promised date + grace
                   >= ordered quantity x (1 - tolerance). Strictest measure.
                   A due line with no receipts is NOT on time, NOT in full and NOT OTIF: missing
                   receipts are never treated as successful delivery.
completion date    the receipt date at which cumulative received quantity first reached the ordered
                   quantity (NaT if never reached).
days late          completed lines: max(0, completion - promised); short-closed lines:
                   max(0, last receipt - promised); open due lines: max(0, as-of - promised),
                   i.e. lateness still accruing.
lead time          completion date - order date, completed lines only.
open line          not cancelled, not short-closed and not fully received.
overdue line       open line whose promised date is before the as-of date.
quality            rejected quantity / received quantity across all receipts.
cancelled lines    excluded from delivery, quality and spend metrics; counted separately.
short-closed lines closed by the buyer with less than the ordered quantity; they are due lines
                   that fail in-full, and are not open.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .synthetic import SyntheticData


def line_facts(data: SyntheticData, as_of: pd.Timestamp, grace_days: int = 0, tolerance: float = 0.0) -> pd.DataFrame:
    lines = data.po_lines.merge(data.purchase_orders[["po_id", "supplier_id", "category_id", "order_date"]],
                                on="po_id", how="left", validate="many_to_one")
    rec = data.receipts.merge(lines[["po_line_id", "promised_date", "ordered_qty"]], on="po_line_id",
                              how="left", validate="many_to_one")
    deadline = rec["promised_date"] + pd.Timedelta(days=grace_days)
    rec["qty_by_promise"] = rec["received_qty"].where(rec["receipt_date"] <= deadline, 0)
    rec = rec.sort_values(["po_line_id", "receipt_date", "receipt_id"])
    rec["cum_qty"] = rec.groupby("po_line_id")["received_qty"].cumsum()
    required = rec["ordered_qty"] * (1 - tolerance)
    completion = rec[rec["cum_qty"] >= required].groupby("po_line_id")["receipt_date"].min()

    agg = rec.groupby("po_line_id").agg(
        receipts=("receipt_id", "size"),
        received_qty=("received_qty", "sum"),
        rejected_qty=("rejected_qty", "sum"),
        qty_by_promise=("qty_by_promise", "sum"),
        first_receipt_date=("receipt_date", "min"),
        last_receipt_date=("receipt_date", "max"),
    )
    f = lines.merge(agg, left_on="po_line_id", right_index=True, how="left", validate="one_to_one")
    for col in ["receipts", "received_qty", "rejected_qty", "qty_by_promise"]:
        f[col] = f[col].fillna(0).astype("int64")
    f["completion_date"] = f["po_line_id"].map(completion)

    deadline = f["promised_date"] + pd.Timedelta(days=grace_days)
    required = f["ordered_qty"] * (1 - tolerance)
    f["line_value"] = f["ordered_qty"] * f["unit_price"]
    f["due"] = ~f["cancelled"] & (f["promised_date"] <= as_of)
    f["on_time"] = f["due"] & f["first_receipt_date"].notna() & (f["first_receipt_date"] <= deadline)
    f["in_full"] = f["due"] & (f["received_qty"] >= required)
    f["otif"] = f["due"] & (f["qty_by_promise"] >= required)
    f["complete"] = f["completion_date"].notna()
    f["open"] = ~f["cancelled"] & ~f["short_closed"] & ~f["complete"]
    f["overdue"] = f["open"] & (f["promised_date"] < as_of)
    f["partial_received"] = f["open"] & (f["received_qty"] > 0)

    late_completed = (f["completion_date"] - f["promised_date"]).dt.days.clip(lower=0)
    late_open = (as_of - f["promised_date"]).dt.days.clip(lower=0)
    late_short = (f["last_receipt_date"].fillna(f["short_close_date"]) - f["promised_date"]).dt.days.clip(lower=0)
    f["days_late"] = np.select([f["complete"], f["short_closed"]], [late_completed, late_short], late_open)
    f["days_late"] = f["days_late"].where(f["due"])
    f["lead_time_days"] = (f["completion_date"] - f["order_date"]).dt.days
    f["open_qty"] = np.where(f["open"], f["ordered_qty"] - f["received_qty"], 0)
    f["open_value"] = f["open_qty"] * f["unit_price"]
    f["status"] = np.select(
        [f["cancelled"], f["complete"], f["short_closed"], f["overdue"], f["open"]],
        ["Cancelled", "Received in full", "Closed short", "Open - overdue", "Open - not yet due"],
        "Unknown",
    )
    f["due_period"] = np.where(f["promised_date"] < as_of - pd.DateOffset(years=1) + pd.Timedelta(days=1), "prior_12m", "last_12m")
    return f


def _rates(g: pd.DataFrame) -> pd.Series:
    due = g[g["due"]]
    completed = g[g["complete"] & ~g["cancelled"]]
    lt = completed["lead_time_days"]
    n_due = len(due)
    received = g.loc[~g["cancelled"], "received_qty"].sum()
    late = due[due["days_late"] > 0]
    return pd.Series({
        "lines": len(g),
        "cancelled_lines": int(g["cancelled"].sum()),
        "due_lines": n_due,
        "on_time_lines": int(due["on_time"].sum()),
        "in_full_lines": int(due["in_full"].sum()),
        "otif_lines": int(due["otif"].sum()),
        "on_time_rate": due["on_time"].mean() if n_due else np.nan,
        "in_full_rate": due["in_full"].mean() if n_due else np.nan,
        "otif_rate": due["otif"].mean() if n_due else np.nan,
        "late_lines": len(late),
        "avg_days_late_all_due": due["days_late"].mean() if n_due else np.nan,
        "avg_days_late_when_late": late["days_late"].mean() if len(late) else 0.0,
        "completed_lines": len(completed),
        "avg_lead_time": lt.mean() if len(lt) else np.nan,
        "lead_time_sd": lt.std(ddof=1) if len(lt) > 1 else np.nan,
        "lead_time_cv": (lt.std(ddof=1) / lt.mean()) if len(lt) > 1 and lt.mean() else np.nan,
        "lead_time_p90": lt.quantile(0.9) if len(lt) else np.nan,
        "received_qty": int(received),
        "rejected_qty": int(g.loc[~g["cancelled"], "rejected_qty"].sum()),
        "reject_rate": (g.loc[~g["cancelled"], "rejected_qty"].sum() / received) if received else np.nan,
        "short_closed_lines": int(g["short_closed"].sum()),
        "open_lines": int(g["open"].sum()),
        "overdue_lines": int(g["overdue"].sum()),
        "overdue_value": float(g.loc[g["overdue"], "open_value"].sum()),
        "partial_open_lines": int(g["partial_received"].sum()),
        "spend": float(g.loc[~g["cancelled"], "line_value"].sum()),
        "standard_value": float((g.loc[~g["cancelled"], "ordered_qty"] * g.loc[~g["cancelled"], "standard_price"]).sum()),
    })


def supplier_performance(facts: pd.DataFrame) -> pd.DataFrame:
    out = facts.groupby("supplier_id").apply(_rates, include_groups=False).reset_index()
    int_cols = [c for c in out.columns if c.endswith("_lines") or c in ("lines", "received_qty", "rejected_qty")]
    out[int_cols] = out[int_cols].astype("int64")
    total = out["spend"].sum()
    out["share_of_total_spend"] = out["spend"] / total
    out["ppv_amount"] = out["spend"] - out["standard_value"]
    out["ppv_pct"] = out["ppv_amount"] / out["standard_value"]

    # Category share: spend of the supplier within each category it serves (largest share reported)
    cat = facts[~facts["cancelled"]].groupby(["category_id", "supplier_id"])["line_value"].sum().reset_index()
    cat["category_share"] = cat["line_value"] / cat.groupby("category_id")["line_value"].transform("sum")
    cat["suppliers_in_category"] = cat.groupby("category_id")["supplier_id"].transform("nunique")
    top = cat.sort_values(["supplier_id", "category_share"], ascending=[True, False]).groupby("supplier_id").head(1)
    out = out.merge(top[["supplier_id", "category_id", "category_share", "suppliers_in_category"]].rename(
        columns={"category_id": "main_category_id", "category_share": "max_category_share"}),
        on="supplier_id", how="left", validate="one_to_one")

    trend = facts[facts["due"]].groupby(["supplier_id", "due_period"])["otif"].agg(["mean", "size"]).unstack()
    for period in ["prior_12m", "last_12m"]:
        out[f"otif_{period}"] = out["supplier_id"].map(trend[("mean", period)]) if ("mean", period) in trend else np.nan
        out[f"due_lines_{period}"] = out["supplier_id"].map(trend[("size", period)]).fillna(0).astype("int64") if ("size", period) in trend else 0
    out["otif_change"] = out["otif_last_12m"] - out["otif_prior_12m"]
    return out


def category_performance(facts: pd.DataFrame) -> pd.DataFrame:
    return facts.groupby("category_id").apply(_rates, include_groups=False).reset_index()


def monthly_otif(facts: pd.DataFrame) -> pd.DataFrame:
    due = facts[facts["due"]].copy()
    due["month"] = due["promised_date"].dt.to_period("M").dt.to_timestamp()
    return due.groupby(["month"]).agg(due_lines=("po_line_id", "size"), otif_lines=("otif", "sum"),
                                      on_time_lines=("on_time", "sum")).assign(
        otif_rate=lambda d: d["otif_lines"] / d["due_lines"]).reset_index()


def monthly_otif_by_supplier(facts: pd.DataFrame) -> pd.DataFrame:
    due = facts[facts["due"]].copy()
    due["quarter"] = due["promised_date"].dt.to_period("Q").astype(str)
    return due.groupby(["supplier_id", "quarter"]).agg(due_lines=("po_line_id", "size"), otif_lines=("otif", "sum")).assign(
        otif_rate=lambda d: d["otif_lines"] / d["due_lines"]).reset_index()
