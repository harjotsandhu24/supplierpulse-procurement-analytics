"""Transparent supplier scorecard (Part B, synthetic data).

Two separate views, because a supplier can perform well and still be a dependency risk:

PERFORMANCE SCORE (0-100)
    Each component is scaled linearly between a "poor" value (0 points) and a "target" value
    (100 points), clipped to [0, 100], then weighted:

        OTIF rate                     40%   higher is better   (poor 70%,  target 95%)
        Quality reject rate           25%   lower is better    (poor 5%,   target 0.5%)
        Lead-time variability (SD)    20%   lower is better    (poor 7 d,  target 2 d)
        Average days late (due lines) 15%   lower is better    (poor 5 d,  target 0 d)

    Missing components are NOT scored as poor. If a component cannot be measured (for example
    fewer than 20 completed lines for lead-time variability) it is dropped and the remaining
    weights are re-normalised; the row is marked `reweighted`.

EVIDENCE RULE
    >= 30 due lines  -> "Ranked"
    10-29 due lines  -> "Provisional" (score shown, not ranked)
    < 10 due lines   -> "Insufficient evidence" (no score, no rank)

RANKING
    Competition ranking on the score rounded to one decimal among Ranked suppliers only:
    rank = 1 + number of ranked suppliers with a strictly higher score, so ties share a rank.

DEPENDENCY RISK (separate from performance)
    High   : sole supplier in a category, or >= 60% of a category's spend, or >= 15% of total spend
    Medium : >= 35% of a category's spend or >= 8% of total spend
    Low    : otherwise
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import Settings

COMPONENTS = [
    # (component name, metric column, weight key, target key, poor key, higher_is_better)
    ("otif", "otif_rate", "weight_otif", "otif_target", "otif_poor", True),
    ("quality", "reject_rate", "weight_quality", "reject_rate_target", "reject_rate_poor", False),
    ("leadtime_consistency", "lead_time_sd", "weight_leadtime_consistency", "leadtime_sd_target", "leadtime_sd_poor", False),
    ("lateness", "avg_days_late_all_due", "weight_lateness", "avg_days_late_target", "avg_days_late_poor", False),
]


def scale(value: float, target: float, poor: float, higher_is_better: bool) -> float:
    """Linear 0-100 score between poor (0) and target (100), clipped."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return float("nan")
    if higher_is_better:
        raw = (value - poor) / (target - poor)
    else:
        raw = (poor - value) / (poor - target)
    return float(min(1.0, max(0.0, raw)) * 100.0)


def evidence_status(due_lines: int, cfg: dict) -> str:
    if due_lines >= cfg["min_lines_ranked"]:
        return "Ranked"
    if due_lines >= cfg["min_lines_provisional"]:
        return "Provisional"
    return "Insufficient evidence"


def tier(score: float, cfg: dict) -> str:
    if np.isnan(score):
        return "Not scored"
    if score >= cfg["tier_preferred"]:
        return "Preferred"
    if score >= cfg["tier_acceptable"]:
        return "Acceptable"
    if score >= cfg["tier_improve"]:
        return "Improvement needed"
    return "At risk"


def competition_rank(scores: pd.Series, eligible: pd.Series) -> pd.Series:
    rounded = scores.round(1)
    ranks = pd.Series(np.nan, index=scores.index)
    pool = rounded[eligible]
    for idx in pool.index:
        ranks[idx] = 1 + int((pool > pool[idx]).sum())
    return ranks


def dependency_level(row: pd.Series, exc: dict) -> str:
    if (row["suppliers_in_category"] == 1
            or row["max_category_share"] >= exc["high_dependency_category_share"]
            or row["share_of_total_spend"] >= exc["high_dependency_total_share"]):
        return "High"
    if (row["max_category_share"] >= exc["medium_dependency_category_share"]
            or row["share_of_total_spend"] >= exc["medium_dependency_total_share"]):
        return "Medium"
    return "Low"


def quadrant(score: float, dependency: str, status: str, cfg: dict) -> str:
    if status == "Insufficient evidence":
        return "Insufficient evidence"
    good = score >= cfg["tier_acceptable"]
    if dependency == "High":
        return "Strategic - protect and monitor" if good else "Critical - act now"
    return "Maintain" if good else "Develop or replace"


def build_scorecard(perf: pd.DataFrame, settings: Settings) -> pd.DataFrame:
    cfg = settings.scorecard
    exc = settings.exceptions
    sc = perf.copy()
    sc.loc[sc["completed_lines"] < exc["min_completed_for_variability"], "lead_time_sd"] = np.nan

    sc["evidence_status"] = [evidence_status(int(n), cfg) for n in sc["due_lines"]]
    weighted = np.zeros(len(sc))
    weight_used = np.zeros(len(sc))
    for name, col, wkey, tkey, pkey, hib in COMPONENTS:
        comp = sc[col].apply(lambda v, t=cfg[tkey], p=cfg[pkey], h=hib: scale(v, t, p, h))
        sc[f"score_{name}"] = comp
        has = comp.notna().to_numpy()
        weighted += np.where(has, comp.fillna(0).to_numpy() * cfg[wkey], 0.0)
        weight_used += np.where(has, cfg[wkey], 0.0)
    sc["weight_used"] = weight_used
    sc["reweighted"] = weight_used < 0.999999
    sc["performance_score"] = np.where(weight_used > 0, weighted / np.where(weight_used > 0, weight_used, 1), np.nan)
    sc.loc[sc["evidence_status"] == "Insufficient evidence", "performance_score"] = np.nan
    sc["performance_score"] = sc["performance_score"].round(1)

    sc["rank"] = competition_rank(sc["performance_score"], sc["evidence_status"] == "Ranked").astype("Int64")
    sc["performance_tier"] = [tier(s, cfg) for s in sc["performance_score"]]
    sc["dependency_risk"] = sc.apply(dependency_level, axis=1, exc=exc)
    sc["action_quadrant"] = [quadrant(s, d, st, cfg) for s, d, st in zip(sc["performance_score"], sc["dependency_risk"], sc["evidence_status"])]
    return sc.sort_values(["rank", "performance_score", "supplier_id"], ascending=[True, False, True], na_position="last").reset_index(drop=True)
