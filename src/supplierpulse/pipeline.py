"""End-to-end SupplierPulse pipeline.

    python -m supplierpulse.pipeline            # analysis, tables, DuckDB, SQL, workbook, dashboard, brief, audit
    python -m supplierpulse.pipeline --render   # also renders screenshots and the PDF brief (needs Microsoft Edge)

The pipeline reads only the pinned public snapshot in data/public/ (plus config), so a clean
clone reproduces every published number.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from . import (database, delivery, exceptions, ingest, price, recommendations, scenarios, scoring, spend,
               synthetic, transform, validate)
from .config import Settings, load_settings

PUBLIC_VENDOR_ROWS = 150  # published vendor tables list the top 150 vendors (all Pareto A vendors); the rest are aggregated


@dataclass
class Results:
    settings: Settings
    clean: validate.CleanResult
    model: transform.AustinModel
    kpis: dict
    fy_spend: pd.DataFrame
    vendors: pd.DataFrame
    categories: pd.DataFrame
    families: pd.DataFrame
    family_trend: pd.DataFrame
    prices: price.PriceResult
    syn: synthetic.SyntheticData
    facts: pd.DataFrame
    performance: pd.DataFrame
    scorecard: pd.DataFrame
    monthly_otif: pd.DataFrame
    register: pd.DataFrame
    definitions: pd.DataFrame
    realloc: pd.DataFrame
    otif_scenario: pd.DataFrame
    price_scenario: pd.DataFrame
    actions: pd.DataFrame
    syn_kpis: dict = field(default_factory=dict)
    headline: dict = field(default_factory=dict)


def analyse(settings: Settings) -> Results:
    raw = ingest.load_snapshot(settings)
    clean = validate.clean_austin(raw, settings)
    model = transform.build_model(clean.lines, settings)

    k = spend.kpis(model.lines, model.headers)
    fy = spend.spend_by_fiscal_year(model.lines, settings)
    vendors = spend.vendor_spend(model.lines)
    cats = spend.category_concentration(model.lines)
    fams = spend.family_spend(model.lines)
    ftrend = spend.family_trend(model.lines)
    prices = price.analyse_prices(model.lines, settings)

    syn = synthetic.generate(settings)
    facts = delivery.line_facts(syn, synthetic.as_of(settings), settings.synthetic["on_time_grace_days"],
                                settings.synthetic["in_full_tolerance"])
    perf = delivery.supplier_performance(facts)
    sc = scoring.build_scorecard(perf, settings)
    sc = sc.merge(syn.suppliers[["supplier_id", "supplier_name", "design_note"]], on="supplier_id", validate="one_to_one")

    reg = exceptions.build_register(
        exceptions.observed_exceptions(cats, vendors, prices, settings),
        exceptions.synthetic_exceptions(sc, facts, syn.suppliers, settings),
    )
    critical = sc[sc["action_quadrant"] == "Critical - act now"]
    realloc_frames = []
    for r in critical.itertuples():
        # Alternative = best-scoring ranked supplier in the same main category
        alts = sc[(sc["main_category_id"] == r.main_category_id) & (sc["supplier_id"] != r.supplier_id)
                  & (sc["evidence_status"] == "Ranked")].sort_values("performance_score", ascending=False)
        if len(alts):
            realloc_frames.append(scenarios.reallocation(facts, r.main_category_id, r.supplier_id, alts.iloc[0]["supplier_id"], settings))
    realloc = pd.concat(realloc_frames, ignore_index=True) if realloc_frames else pd.DataFrame()
    otif_sc = scenarios.otif_improvement(sc, settings)
    price_sc = scenarios.price_harmonisation(prices.summary, settings)
    actions = recommendations.build_actions(reg, sc, realloc, cats, prices.summary, settings)

    due = facts[facts["due"]]
    syn_kpis = {
        "suppliers": int(syn.suppliers.shape[0]),
        "purchase_orders": int(syn.purchase_orders.shape[0]),
        "po_lines": int(syn.po_lines.shape[0]),
        "receipts": int(syn.receipts.shape[0]),
        "due_lines": int(len(due)),
        "otif_rate": float(due["otif"].mean()),
        "on_time_rate": float(due["on_time"].mean()),
        "in_full_rate": float(due["in_full"].mean()),
        "otif_prior_12m": float(due.loc[due["due_period"] == "prior_12m", "otif"].mean()),
        "otif_last_12m": float(due.loc[due["due_period"] == "last_12m", "otif"].mean()),
        "reject_rate": float(facts.loc[~facts["cancelled"], "rejected_qty"].sum() / facts.loc[~facts["cancelled"], "received_qty"].sum()),
        "open_lines": int(facts["open"].sum()),
        "overdue_lines": int(facts["overdue"].sum()),
        "overdue_value": float(facts.loc[facts["overdue"], "open_value"].sum()),
        "cancelled_lines": int(facts["cancelled"].sum()),
        "short_closed_lines": int(facts["short_closed"].sum()),
        "spend": float(facts.loc[~facts["cancelled"], "line_value"].sum()),
        "as_of_date": settings.synthetic["as_of_date"],
        "start_date": settings.synthetic["start_date"],
        "seed": settings.synthetic["seed"],
    }
    res = Results(settings, clean, model, k, fy, vendors, cats, fams, ftrend, prices, syn, facts, perf, sc,
                  delivery.monthly_otif(facts), reg, exceptions.definitions_table(settings), realloc, otif_sc,
                  price_sc, actions, syn_kpis)
    res.headline = headline_findings(res)
    return res


def headline_findings(r: Results) -> dict:
    """Numbers quoted in the README, brief, dashboard and Notion copy (single source of truth)."""
    c = r.settings.concentration
    big = r.categories[r.categories["spend"] >= c["min_category_spend"]]
    r1 = big[big["top_vendor_share"] >= c["single_vendor_share"]]
    r2 = big[(big["hhi"] >= c["hhi_highly_concentrated"])]
    yoy = r.prices.yoy
    trans = yoy[yoy["item_description"].str.contains("TRANSFORMER", na=False)]
    trans_22_23 = trans[(trans["prior_fiscal_year"] == 2022) & (trans["fiscal_year"] == 2023)]
    top_fam = r.families.iloc[0]
    crit = r.scorecard[r.scorecard["action_quadrant"] == "Critical - act now"]
    rr = r.realloc[r.realloc["share_moved"].round(2) == 0.30] if len(r.realloc) else pd.DataFrame()
    a = r.settings.analysis
    return {
        "period_label": f"FY{a['focus_fy_start']}-FY{a['focus_fy_end']}",
        "period_dates": f"1 Oct {a['focus_fy_start'] - 1} - 30 Sep {a['focus_fy_end']}",
        "total_spend": r.kpis["total_spend"],
        "po_count": r.kpis["po_count"],
        "line_count": r.kpis["line_count"],
        "active_vendors": r.kpis["active_vendors"],
        "top10_share": r.kpis["top10_vendor_share"],
        "vendors_for_80pct": r.kpis["vendors_for_80pct"],
        "vendor_hhi": r.kpis["vendor_hhi"],
        "master_agreement_share": r.kpis["master_agreement_share"],
        "top_family": top_fam["spend_family"],
        "top_family_share": float(top_fam["share"]),
        "screened_categories": int(len(big)),
        "screened_category_spend_share": float(big["spend"].sum() / r.kpis["total_spend"]),
        "highly_concentrated_categories": int(len(r2)),
        "highly_concentrated_spend": float(r2["spend"].sum()),
        "single_vendor_categories": int(len(r1)),
        "single_vendor_spend": float(r1["spend"].sum()),
        "largest_single_vendor_category": r1.iloc[0]["class_label"] if len(r1) else "",
        "largest_single_vendor_share": float(r1.iloc[0]["top_vendor_share"]) if len(r1) else float("nan"),
        "largest_single_vendor_spend": float(r1.iloc[0]["spend"]) if len(r1) else float("nan"),
        "largest_single_vendor_name": r1.iloc[0]["top_vendor_name"] if len(r1) else "",
        "transformer_items_22_23": int(len(trans_22_23)),
        "transformer_median_change_22_23": float(trans_22_23["pct_change"].median()) if len(trans_22_23) else float("nan"),
        "transformer_max_change_22_23": float(trans_22_23["pct_change"].max()) if len(trans_22_23) else float("nan"),
        "transformer_spend_fy23": float(trans_22_23["spend"].sum()) if len(trans_22_23) else float("nan"),
        "yoy_items_up_25pct": r.prices.summary["yoy_increases_25pct"],
        "yoy_item_pairs": r.prices.summary["yoy_item_pairs"],
        "comparable_share_of_spend": r.prices.summary["comparable_share_of_total_spend"],
        "price_flagged_lines": r.prices.summary["flagged_lines"],
        "price_opportunity_full": r.prices.summary["modelled_opportunity_full"],
        "price_opportunity_qty_controlled": r.prices.summary["modelled_opportunity_quantity_controlled"],
        "critical_supplier": crit.iloc[0]["supplier_id"] if len(crit) else "",
        "critical_supplier_score": float(crit.iloc[0]["performance_score"]) if len(crit) else float("nan"),
        "critical_otif_prior": float(crit.iloc[0]["otif_prior_12m"]) if len(crit) else float("nan"),
        "critical_otif_last": float(crit.iloc[0]["otif_last_12m"]) if len(crit) else float("nan"),
        "critical_category_share": float(crit.iloc[0]["max_category_share"]) if len(crit) else float("nan"),
        "realloc_to": rr.iloc[0]["to_supplier"] if len(rr) else "",
        "realloc_30_late_lines_avoided": float(rr.iloc[0]["late_lines_avoided"]) if len(rr) else float("nan"),
        "realloc_30_late_lines_before": float(rr.iloc[0]["late_lines_before"]) if len(rr) else float("nan"),
        "realloc_30_cost_avoided": float(rr.iloc[0]["late_cost_avoided"]) if len(rr) else float("nan"),
        "realloc_30_price_impact": float(rr.iloc[0]["price_impact"]) if len(rr) else float("nan"),
        "ranked_suppliers": int((r.scorecard["evidence_status"] == "Ranked").sum()),
        "provisional_suppliers": int((r.scorecard["evidence_status"] == "Provisional").sum()),
        "insufficient_suppliers": int((r.scorecard["evidence_status"] == "Insufficient evidence").sum()),
        "exceptions_total": int(len(r.register)),
        "actions_high": int((r.actions["priority"] == "High").sum()),
    }


# ---------------------------------------------------------------------------------------------
# Published tables
# ---------------------------------------------------------------------------------------------

def public_vendor_table(vendors: pd.DataFrame, n: int = PUBLIC_VENDOR_ROWS) -> pd.DataFrame:
    """Top-n vendors plus one aggregated row, so small (possibly individual) vendors are not listed."""
    top = vendors.head(n).copy()
    rest = vendors.iloc[n:]
    if len(rest):
        other = {
            "vendor_code": "ALL_OTHER", "vendor_name": f"All other vendors ({len(rest):,})",
            "spend": rest["spend"].sum(), "po_count": rest["po_count"].sum(), "line_count": rest["line_count"].sum(),
            "categories": None, "agreement_spend": rest["agreement_spend"].sum(), "rank": None,
            "share": rest["share"].sum(), "cumulative_share": 1.0,
            "avg_po_value": rest["spend"].sum() / rest["po_count"].sum(),
            "agreement_share": rest["agreement_spend"].sum() / rest["spend"].sum(), "pareto_class": "",
        }
        top = pd.concat([top, pd.DataFrame([other])], ignore_index=True)
    return top


def write_tables(r: Results) -> Path:
    out = r.settings.path("tables_dir")
    out.mkdir(parents=True, exist_ok=True)
    c = r.settings.concentration

    def save(df: pd.DataFrame, name: str) -> None:
        df.to_csv(out / f"{name}.csv", index=False, float_format="%.6f", date_format="%Y-%m-%d")

    save(r.fy_spend, "obs_spend_by_fiscal_year")
    save(public_vendor_table(r.vendors), "obs_vendor_spend_top150")
    save(r.categories[r.categories["spend"] >= c["min_category_spend"]], "obs_category_concentration")
    save(r.families, "obs_spend_family")
    save(r.family_trend.reset_index(), "obs_spend_family_by_year")
    save(r.prices.item_years.drop(columns=["item_key"]), "obs_price_item_years")
    save(r.prices.yoy.drop(columns=["item_key"]), "obs_price_year_over_year")
    save(r.prices.vendor_index[r.prices.vendor_index["comparable_lines"] >= 10], "obs_vendor_price_index")
    save(r.scorecard, "syn_supplier_scorecard")
    save(r.monthly_otif, "syn_monthly_otif")
    save(delivery.category_performance(r.facts), "syn_category_performance")
    save(r.register, "exception_register")
    save(r.definitions, "exception_definitions")
    save(r.realloc, "scenario_reallocation")
    save(r.otif_scenario, "scenario_otif_improvement")
    save(r.price_scenario, "scenario_price_harmonisation")
    save(r.actions, "procurement_action_list")
    metrics = {"observed_kpis": r.kpis, "synthetic_kpis": r.syn_kpis, "price_summary": r.prices.summary,
               "headline": r.headline, "data_quality": r.clean.audit}
    (out.parent / "metrics.json").write_text(json.dumps(metrics, indent=2, default=_json_default) + "\n", encoding="utf-8")
    return out


def write_synthetic(r: Results) -> Path:
    out = r.settings.path("public_dir") / "synthetic"
    out.mkdir(parents=True, exist_ok=True)
    for name in ["suppliers", "categories", "items", "purchase_orders", "po_lines", "receipts"]:
        getattr(r.syn, name).to_csv(out / f"syn_{name}.csv", index=False, date_format="%Y-%m-%d")
    return out


def _json_default(o):
    if isinstance(o, (pd.Timestamp,)):
        return o.strftime("%Y-%m-%d")
    if hasattr(o, "item"):
        return o.item()
    raise TypeError(type(o))


def run(render: bool = False) -> Results:
    settings = load_settings()
    if not ingest.snapshot_path(settings).exists() and ingest.raw_path(settings).exists():
        ingest.build_snapshot(settings)
    print("1/8 Analysing observed and synthetic data ...")
    r = analyse(settings)
    print("2/8 Writing tables and synthetic data ...")
    write_tables(r)
    write_synthetic(r)
    print("3/8 Building DuckDB database and running SQL package ...")
    database.build_database(settings, r.model, r.clean.excluded, r.syn)
    database.run_queries(settings)
    print("4/8 Building Excel workbook ...")
    from . import excel_export
    excel_export.build_workbook(r)
    print("5/8 Building dashboard ...")
    from . import dashboard
    dashboard.build_dashboard(r)
    print("6/8 Building decision brief ...")
    from . import brief
    brief.build_brief(r)
    print("7/8 Writing data-quality audit ...")
    from . import audit
    audit.write_audit(r)
    from .docs_text import write_data_dictionary
    write_data_dictionary(settings.path("docs_dir") / "data_dictionary.md")
    if render:
        print("8/8 Rendering screenshots and PDF (Microsoft Edge via Playwright) ...")
        from . import render as render_mod
        render_mod.render_all(settings)
    else:
        print("8/8 Skipped rendering (use --render)")
    print("Done.")
    return r


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the SupplierPulse pipeline.")
    parser.add_argument("--render", action="store_true", help="render screenshots and PDF brief with Microsoft Edge")
    args = parser.parse_args()
    run(render=args.render)


if __name__ == "__main__":
    main()
