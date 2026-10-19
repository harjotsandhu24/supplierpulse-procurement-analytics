"""What-if scenarios. Every output is a MODELLED estimate under stated assumptions, not a
forecast of realised savings.

A. Volume reallocation (synthetic): move a share of one supplier's annual volume in a category
   to an alternative supplier and estimate the change in late lines, late-line handling cost,
   price impact and category concentration. Uses the last 12 months' observed volumes and OTIF.
     moved_lines       = x * L_from
     late_lines_before = L_from*(1-o_from) + L_to*(1-o_to)
     late_lines_after  = (1-x)*L_from*(1-o_from) + (L_to + x*L_from)*(1-o_to)
     price_impact      = x * S_from * ((1+ppv_to)/(1+ppv_from) - 1)   (positive = costs more)
   It assumes the alternative supplier keeps its current OTIF and pricing at the higher volume,
   which must be validated (capacity, contract terms) before acting.

B. OTIF improvement (synthetic): late lines and handling cost avoided if a supplier reached the
   target OTIF on its last-12-month volume.

C. Price harmonisation (observed, City of Austin): what the above-baseline comparable-item lines
   would have cost at the item-year median, at several capture rates.
"""

from __future__ import annotations

import pandas as pd

from .config import Settings
from .spend import hhi


def last_12m_volumes(facts: pd.DataFrame, category_id: str) -> pd.DataFrame:
    f = facts[(facts["category_id"] == category_id) & (facts["due_period"] == "last_12m") & facts["due"]]
    spend = facts[(facts["category_id"] == category_id) & ~facts["cancelled"] & (facts["due_period"] == "last_12m")]
    vol = f.groupby("supplier_id").agg(due_lines=("po_line_id", "size"), otif_lines=("otif", "sum"))
    vol["otif_rate"] = vol["otif_lines"] / vol["due_lines"]
    vol["spend"] = spend.groupby("supplier_id")["line_value"].sum()
    vol["standard_value"] = spend.assign(sv=spend["ordered_qty"] * spend["standard_price"]).groupby("supplier_id")["sv"].sum()
    vol["ppv_pct"] = vol["spend"] / vol["standard_value"] - 1
    return vol.reset_index()


def reallocation(facts: pd.DataFrame, category_id: str, from_id: str, to_id: str, settings: Settings) -> pd.DataFrame:
    vol = last_12m_volumes(facts, category_id).set_index("supplier_id")
    cost = settings.scenario["cost_per_late_line"]
    lf, lt = vol.at[from_id, "due_lines"], vol.at[to_id, "due_lines"]
    of, ot = vol.at[from_id, "otif_rate"], vol.at[to_id, "otif_rate"]
    sf = vol.at[from_id, "spend"]
    pf, pt = vol.at[from_id, "ppv_pct"], vol.at[to_id, "ppv_pct"]
    base_spend = vol["spend"]
    rows = []
    for x in settings.scenario["reallocation_shares"]:
        before = lf * (1 - of) + lt * (1 - ot)
        after = (1 - x) * lf * (1 - of) + (lt + x * lf) * (1 - ot)
        moved_spend = x * sf
        spend_after = base_spend.copy()
        spend_after[from_id] -= moved_spend
        spend_after[to_id] += moved_spend
        shares_after = spend_after / spend_after.sum()
        rows.append({
            "category_id": category_id, "from_supplier": from_id, "to_supplier": to_id, "share_moved": x,
            "lines_moved": x * lf, "spend_moved": moved_spend,
            "late_lines_before": before, "late_lines_after": after, "late_lines_avoided": before - after,
            "late_cost_avoided": (before - after) * cost,
            "price_impact": moved_spend * ((1 + pt) / (1 + pf) - 1),
            "from_share_after": shares_after[from_id], "category_hhi_after": hhi(shares_after),
            "otif_from": of, "otif_to": ot, "cost_per_late_line": cost,
        })
    out = pd.DataFrame(rows)
    out["net_modelled_benefit"] = out["late_cost_avoided"] - out["price_impact"]
    return out


def otif_improvement(scorecard: pd.DataFrame, settings: Settings) -> pd.DataFrame:
    target = settings.scorecard["otif_target"]
    cost = settings.scenario["cost_per_late_line"]
    sc = scorecard[scorecard["evidence_status"] == "Ranked"].copy()
    sc["otif_basis"] = sc["otif_last_12m"].fillna(sc["otif_rate"])
    sc["lines_basis"] = sc["due_lines_last_12m"]
    sc["late_lines_current"] = sc["lines_basis"] * (1 - sc["otif_basis"])
    sc["late_lines_at_target"] = sc["lines_basis"] * (1 - sc[["otif_basis"]].clip(lower=target)["otif_basis"])
    sc["late_lines_avoided"] = sc["late_lines_current"] - sc["late_lines_at_target"]
    sc["late_cost_avoided"] = sc["late_lines_avoided"] * cost
    sc["otif_target"] = target
    cols = ["supplier_id", "otif_basis", "otif_target", "lines_basis", "late_lines_current", "late_lines_at_target",
            "late_lines_avoided", "late_cost_avoided"]
    return sc[cols].sort_values(["late_cost_avoided", "supplier_id"], ascending=[False, True]).reset_index(drop=True)


def price_harmonisation(price_summary: dict, settings: Settings) -> pd.DataFrame:
    full = price_summary["modelled_opportunity_full"]
    a = settings.analysis
    period = f"FY{a['focus_fy_start']}-FY{a['focus_fy_end']} total ({a['focus_fy_end'] - a['focus_fy_start'] + 1} years, not annual)"
    return pd.DataFrame([{
        "capture_rate": r, "modelled_opportunity": full * r, "basis_flagged_lines": price_summary["flagged_lines"],
        "basis_period": period,
    } for r in settings.scenario["price_capture_rates"]])
