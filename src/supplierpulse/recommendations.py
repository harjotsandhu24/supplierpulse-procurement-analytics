"""Prioritised procurement action list.

Each action is derived from exception-register rows by an explicit rule (below); text is
templated from the calculated values so the action list always matches the analysis.

Priority rules
--------------
Observed (City of Austin)
  R1 single-vendor category       recurring (>= 12 orders over >= 3 fiscal years): High if spend >= $10M, else Medium;
                                   concentrated in a few large orders: Low (verify one-time purchase)
  R6 year-over-year price increase grouped by NIGP class; High if the affected items' spend >= $5M, Medium if
                                   >= $250k, otherwise left in the register only
  R5 price above item-year median  Medium (aggregated)
  R2 highly concentrated category  Medium for the three largest by spend (aggregated)
  R4 recurring standalone buying   Low (aggregated, top three classes named)
  R3 vendor share of total spend   Low
Synthetic demonstration
  Supplier in the "Critical - act now" quadrant                       High
  S1 chronically late (not critical)                                   High if >= 5% of spend, else Medium
  S4 incomplete deliveries / S5 quality / S6 PPV                       Medium
  S7 overdue lines                                                     Medium (aggregated)
  S8 dependency where performance is good ("Strategic")                Low
"""

from __future__ import annotations

import pandas as pd

from .config import Settings

PRIORITY_ORDER = {"High": 1, "Medium": 2, "Low": 3}


def _m(x: float) -> str:
    return f"${x / 1e6:,.1f}M" if abs(x) >= 1e6 else f"${x:,.0f}"


def build_actions(reg: pd.DataFrame, scorecard: pd.DataFrame, realloc: pd.DataFrame, cat_conc: pd.DataFrame,
                  price_summary: dict, settings: Settings) -> pd.DataFrame:
    a = settings.analysis
    period = f"FY{a['focus_fy_start']}-FY{a['focus_fy_end']}"
    acts: list[dict] = []

    def add(priority, origin, entity, issue, metric, significance, action, limitation, rules):
        acts.append({"priority": priority, "data_origin": origin, "supplier_or_category": entity, "issue": issue,
                     "supporting_metric": metric, "business_significance": significance,
                     "recommended_action": action, "data_limitation": limitation, "source_rules": rules})

    obs = "Observed - City of Austin"
    syn = "Synthetic demonstration"

    # --- Observed --------------------------------------------------------------------------
    act_cfg = settings.raw["actions"]
    for r in reg[reg["rule"] == "R1"].itertuples():
        recurring = "(recurring)" in r.detail
        if recurring:
            priority = "High" if r.exposure_usd >= act_cfg["high_priority_category_spend"] else "Medium"
            significance = ("An exposure to investigate: if this vendor were disrupted or repriced, the purchasing record "
                            "shows no other vendor supplying the category at scale.")
            action = ("Review the award history and confirm whether a tested contingency source (secondary award or backup "
                      "agreement) exists before the next renewal.")
        else:
            priority = "Low"
            significance = "Concentration comes from a few large orders, which suggests project or one-time buys rather than ongoing dependency."
            action = "Verify the orders were one-time purchases; no supply-continuity action unless the demand recurs."
        add(priority, obs, r.entity_name, "Single-vendor concentration (exposure to review)",
            f"Top vendor holds {r.value:.0%} of {_m(r.exposure_usd)} {period} spend ({r.detail})", significance, action,
            "Concentration is not evidence of a poor or unsuitable vendor and may result from a deliberate competitive "
            "award. Award values only: the data contains no delivery or quality records.", r.exception_id)

    r6 = reg[reg["rule"] == "R6"].copy()
    if len(r6):
        r6["cls"] = r6["entity_id"].str[:3]
        labels = cat_conc.set_index("nigp_class")["class_label"]
        for cls, g in r6.groupby("cls"):
            spend = g["exposure_usd"].sum()
            if spend < act_cfg["min_price_action_spend"]:
                continue  # remains in the exception register; too small to be a management action
            add("High" if spend >= act_cfg["high_priority_price_spend"] else "Medium", obs, labels.get(cls, cls), "Sharp year-over-year price increases",
                f"{len(g)} comparable item(s) rose >= 25% year over year; median increase {g['value'].median():.0%}; "
                f"{_m(spend)} spent on them in the later year",
                "Budget exposure: identical items cost materially more from one year to the next.",
                "Benchmark against market price indices, use index-linked price-adjustment clauses with caps, and plan "
                "forward buys or multi-award agreements for long-lead items.",
                "Observed price increases may reflect industry-wide shortages (e.g. 2022-23 transformer market) rather "
                "than supplier behaviour; specification changes cannot be fully ruled out.",
                ", ".join(g["exception_id"].head(5)) + (" ..." if len(g) > 5 else ""))

    r5 = reg[reg["rule"] == "R5"]
    if len(r5):
        add("Medium", obs, f"{len(r5)} comparable item-years", "Same-item price dispersion within a fiscal year",
            f"{price_summary['flagged_lines']} lines priced >= {settings.price['above_baseline_ratio']}x their item-year "
            f"median; modelled excess {_m(price_summary['modelled_opportunity_full'])} over {period}",
            "Paying different prices for the same item in the same year signals pricing that agreements could standardise.",
            "Review the largest flagged item-years with buyers; where differences are not explained by urgency, order size "
            "or specification, standardise pricing in the governing agreement.",
            f"Covers only the {price_summary['comparable_share_of_total_spend']:.0%} of spend that is like-for-like comparable. "
            "The excess is a modelled opportunity, not a realised saving.", ", ".join(r5["exception_id"].head(5)) + " ...")

    r2 = reg[reg["rule"] == "R2"].head(3)
    if len(r2):
        names = "; ".join(r2["entity_name"].str.slice(0, 45))
        add("Medium", obs, "Largest highly concentrated categories", "Limited competition in high-spend categories",
            f"{(reg['rule'] == 'R2').sum()} categories have HHI >= {settings.concentration['hhi_highly_concentrated']:,}; "
            f"largest three ({_m(r2['exposure_usd'].sum())}): {names}",
            "High concentration reduces negotiating leverage and resilience.",
            "At the next solicitation, test the market for additional qualified vendors or multiple awards where "
            "technically feasible (some categories, such as radio systems, may be locked to a platform).",
            "HHI is calculated on award value by vendor code; related companies with different codes are counted separately.",
            ", ".join(r2["exception_id"]))

    r4 = reg[reg["rule"] == "R4"].head(3)
    if len(r4):
        add("Low", obs, "Recurring standalone purchasing", "Repeated buying outside master agreements",
            f"{(reg['rule'] == 'R4').sum()} classes meet the rule; top three: "
            + "; ".join(f"{n[:40]} ({_m(v)})" for n, v in zip(r4["entity_name"], r4["exposure_usd"])),
            "Recurring one-off contracts and POs forgo the pricing and administrative efficiency of a term agreement.",
            "Assess whether recurring standalone demand in these classes can be aggregated into term agreements.",
            "Many standalone contracts are legitimate one-time purchases or construction-related; this is a screening list.",
            ", ".join(r4["exception_id"]))

    for r in reg[reg["rule"] == "R3"].itertuples():
        add("Low", obs, r.entity_name, "Vendor share of total spend",
            f"{r.value:.1%} of all {period} spend ({_m(r.exposure_usd)})",
            "Largest single-vendor exposure across the whole portfolio.",
            "Monitor as part of supplier relationship management; no action indicated by share alone.",
            "Share alone is not a performance problem.", r.exception_id)

    # --- Synthetic -------------------------------------------------------------------------
    names = scorecard.set_index("supplier_id")
    critical = scorecard[scorecard["action_quadrant"] == "Critical - act now"]
    for r in critical.itertuples():
        sc_rules = reg[(reg["entity_id"] == r.supplier_id)]
        rr = realloc[(realloc["from_supplier"] == r.supplier_id) & (realloc["share_moved"].round(2) == 0.30)]
        scen = ""
        if len(rr):
            x = rr.iloc[0]
            scen = (f" Modelled scenario: moving 30% of its {x['category_id']} volume to {x['to_supplier']} would avoid an "
                    f"estimated {x['late_lines_avoided']:.0f} late lines a year, if that supplier kept its current OTIF.")
        add("High", syn, f"{r.supplier_id} (Synthetic Supplier {r.supplier_id[-2:]})", "High-dependency supplier with poor, deteriorating delivery",
            f"Score {r.performance_score:.0f}/100 (rank {r.rank}); OTIF {r.otif_prior_12m:.0%} -> {r.otif_last_12m:.0%}; "
            f"{r.max_category_share:.0%} of category spend",
            f"The largest supplier in its category missed OTIF on {1 - r.otif_last_12m:.0%} of due lines in the last "
            "12 months, so its delays reach many orders.",
            "Hold a formal performance review with a corrective action plan and a 95% OTIF target; qualify the "
            "alternative supplier for part of the volume." + scen,
            "Synthetic data: illustrates the method only. Assumes the alternative supplier can absorb volume at its current OTIF.",
            ", ".join(sc_rules["exception_id"]))
    crit_ids = set(critical["supplier_id"])

    for r in reg[(reg["rule"] == "S1") & ~reg["entity_id"].isin(crit_ids)].itertuples():
        row = names.loc[r.entity_id]
        add("High" if row["share_of_total_spend"] >= 0.05 else "Medium", syn, f"{r.entity_id} ({r.entity_name})",
            "Chronically late supplier", f"OTIF {r.value:.0%}; lead-time SD {row['lead_time_sd']:.1f} days",
            "Late deliveries disrupt planned work and force expediting.",
            "Re-baseline quoted lead times against actual history, require advance shipping notice of delays, and shift "
            "volume toward better-performing approved suppliers if no improvement within one quarter.",
            "Synthetic data: illustrates the method only.", r.exception_id)

    templates = {
        "S4": ("Recurring incomplete deliveries", "Short and split shipments leave work orders waiting for remaining quantities.",
               "Agree a minimum line fill-rate in the contract and require backorder notification at order acknowledgement."),
        "S5": ("Quality rejections", "Rejected units create rework, returns and stock shortfalls.",
               "Issue a supplier corrective action request, increase incoming inspection until rejects fall below 2%."),
        "S6": ("Paid prices above contract", "Paying above contract price erodes negotiated savings.",
               "Audit invoices against contract prices and recover overcharges; enforce price-file controls in purchasing."),
    }
    for rule, (issue, sig, act) in templates.items():
        for r in reg[reg["rule"] == rule].itertuples():
            metric = f"{r.metric}: {r.value:.1%} ({r.detail})"
            add("Medium", syn, f"{r.entity_id} ({r.entity_name})", issue, metric, sig, act,
                "Synthetic data: illustrates the method only.", r.exception_id)

    s7 = reg[reg["rule"] == "S7"]
    if len(s7):
        add("Medium", syn, f"{len(s7)} overdue PO lines", "Overdue open purchase-order lines",
            f"{len(s7)} lines past promised date; oldest {s7['value'].max():.0f} days; {_m(s7['exposure_usd'].sum())} outstanding",
            "Open overdue lines are unplanned shortages for the requesting department.",
            "Expedite the oldest lines with suppliers, confirm new dates, and cancel lines that are no longer needed.",
            "Synthetic data: illustrates the method only.", ", ".join(s7["exception_id"].head(5)) + (" ..." if len(s7) > 5 else ""))

    strategic = scorecard[scorecard["action_quadrant"] == "Strategic - protect and monitor"]
    for r in strategic.itertuples():
        add("Low", syn, f"{r.supplier_id} (Synthetic Supplier {r.supplier_id[-2:]})", "Good performer with high dependency",
            f"Score {r.performance_score:.0f}/100; {r.max_category_share:.0%} of category spend"
            + ("; sole supplier" if r.suppliers_in_category == 1 else ""),
            "Performance is good, but the category has little or no fallback if this supplier is disrupted.",
            "Protect the relationship; document a contingency source and review it annually rather than moving volume.",
            "Synthetic data: illustrates the method only.", "S8")

    out = pd.DataFrame(acts)
    out["priority_order"] = out["priority"].map(PRIORITY_ORDER)
    out = out.sort_values(["priority_order", "data_origin"], kind="stable").reset_index(drop=True)
    out.insert(0, "action_id", [f"A{i:02d}" for i in range(1, len(out) + 1)])
    return out.drop(columns="priority_order")
