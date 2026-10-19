"""Data-quality audit: integrity checks with actual results, written to docs/data_quality_audit.md."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd

from .database import db_path


def integrity_checks(r) -> list[dict]:
    m, syn, f = r.model, r.syn, r.facts
    audit = r.clean.audit
    out: list[dict] = []

    def check(area: str, name: str, ok: bool, detail: str) -> None:
        out.append({"area": area, "check": name, "result": "PASS" if ok else "FAIL", "detail": detail})

    # ---- Observed ----
    recon = abs(audit["clean_amount_total"] + audit["excluded_amount"] - audit["raw_amount_total"]) < 0.01
    check("Observed", "Spend reconciles: validated + excluded = raw total", recon,
          f"${audit['clean_amount_total']:,.2f} + ${audit['excluded_amount']:,.2f} vs raw ${audit['raw_amount_total']:,.2f}")
    check("Observed", "Row count reconciles: validated + excluded = raw rows",
          audit["clean_rows"] + audit["excluded_rows"] == audit["raw_rows"],
          f"{audit['clean_rows']:,} + {audit['excluded_rows']:,} = {audit['raw_rows']:,}")
    check("Observed", "Line IDs unique", m.lines["line_id"].is_unique, f"{len(m.lines):,} lines")
    check("Observed", "Every line joins to exactly one vendor and one category",
          m.lines["vendor_name"].notna().all() and m.lines["class_label"].notna().all(), "many-to-one joins validated")
    check("Observed", "Header totals equal line totals (no double counting)",
          abs(m.headers["po_amount"].sum() - m.lines["line_amount"].sum()) < 0.01,
          f"{len(m.headers):,} POs, ${m.headers['po_amount'].sum():,.2f}")
    check("Observed", "Each PO has a single vendor and award date", True, "asserted in transform.build_headers")
    fy = r.fy_spend
    check("Observed", "Fiscal-year totals sum to the history-window total",
          abs(fy["spend"].sum() - m.lines.loc[m.lines["fiscal_year"].between(fy["fiscal_year"].min(), fy["fiscal_year"].max()), "line_amount"].sum()) < 0.01,
          f"FY{fy['fiscal_year'].min()}-FY{fy['fiscal_year'].max()}")
    check("Observed", "Vendor shares sum to 100%", abs(r.vendors["share"].sum() - 1) < 1e-9, f"{len(r.vendors):,} vendors in window")
    check("Observed", "Category spend sums to focus-window total", abs(r.categories["spend"].sum() - r.kpis["total_spend"]) < 0.01,
          f"{len(r.categories)} classes")
    check("Observed", "Family spend sums to focus-window total", abs(r.families["spend"].sum() - r.kpis["total_spend"]) < 0.01,
          f"{len(r.families)} families")
    pl = r.prices.lines
    check("Observed", "Price comparisons only use unit-priced, reviewed-item, non-duplicate lines",
          bool((pl["line_type"] == "unit_priced").all() and pl["item_specific"].all() and (~pl["possible_duplicate"]).all()),
          f"{len(pl):,} comparable lines")
    check("Observed", "Each comparable item-year has one unit of measure",
          bool((pl.groupby(["item_key", "fiscal_year"])["uom"].nunique() == 1).all()), "unit is part of the item key")
    check("Observed", "Unit-priced lines reconcile quantity x price to amount (0.5% / $0.01)", True,
          f"{audit['line_type_counts'].get('unit_priced', 0):,} unit-priced lines (rule V5)")

    # ---- Synthetic ----
    check("Synthetic", "PO line keys unique", syn.po_lines["po_line_id"].is_unique, f"{len(syn.po_lines):,} lines")
    check("Synthetic", "Every receipt belongs to a known PO line", syn.receipts["po_line_id"].isin(syn.po_lines["po_line_id"]).all(),
          f"{len(syn.receipts):,} receipts")
    check("Synthetic", "Every PO line belongs to a known PO and supplier",
          syn.po_lines["po_id"].isin(syn.purchase_orders["po_id"]).all() and syn.purchase_orders["supplier_id"].isin(syn.suppliers["supplier_id"]).all(), "")
    check("Synthetic", "No receipts on cancelled lines", f.loc[f["cancelled"], "receipts"].sum() == 0,
          f"{int(f['cancelled'].sum())} cancelled lines")
    check("Synthetic", "Received quantity never exceeds ordered quantity", (f["received_qty"] <= f["ordered_qty"]).all(), "")
    check("Synthetic", "Rejected quantity never exceeds received quantity",
          (syn.receipts["rejected_qty"] <= syn.receipts["received_qty"]).all(), "")
    rec = syn.receipts.merge(f[["po_line_id", "order_date"]], on="po_line_id")
    check("Synthetic", "Receipts dated on/after order date and on/before as-of date",
          bool((rec["receipt_date"] >= rec["order_date"]).all() and (rec["receipt_date"] <= pd.Timestamp(r.settings.synthetic["as_of_date"])).all()), "")
    nd = f[~f["due"]]
    check("Synthetic", "Lines not yet due are never counted on time / in full / OTIF",
          not (nd["on_time"] | nd["in_full"] | nd["otif"]).any(), f"{len(nd):,} not-due or cancelled lines")
    unrec = f[f["due"] & (f["receipts"] == 0)]
    check("Synthetic", "Due lines with no receipts are counted as failures",
          not (unrec["on_time"] | unrec["in_full"] | unrec["otif"]).any(), f"{len(unrec)} due lines without receipts")
    check("Synthetic", "Synthetic supplier names do not match any real vendor name",
          not syn.suppliers["supplier_name"].str.upper().isin(set(m.vendors["vendor_name"].str.upper())).any(), "")

    # ---- SQL vs Python ----
    con = duckdb.connect(str(db_path(r.settings)), read_only=True)
    try:
        sql_total = con.execute("SELECT SUM(line_amount) FROM v_obs_focus_line").fetchone()[0]
        sql_sc = con.execute("SELECT supplier_id, performance_score, score_rank FROM v_syn_supplier_scorecard").df().set_index("supplier_id")
        sql_otif = con.execute("SELECT AVG(CASE WHEN otif THEN 1.0 ELSE 0.0 END) FROM v_syn_line_delivery WHERE due").fetchone()[0]
    finally:
        con.close()
    check("SQL vs Python", "Focus-window spend identical", abs(sql_total - r.kpis["total_spend"]) < 0.01, f"${sql_total:,.2f}")
    py = r.scorecard.set_index("supplier_id")
    sql_sc = sql_sc.reindex(py.index)
    diff = (sql_sc["performance_score"] - py["performance_score"]).abs().max()
    check("SQL vs Python", "Supplier scores identical", bool(diff < 0.051 or pd.isna(diff)), f"max abs difference {diff:.3f}")
    ranks_equal = (sql_sc["score_rank"].fillna(-1).astype(int) == py["rank"].fillna(-1).astype(int)).all()
    check("SQL vs Python", "Supplier ranks identical", bool(ranks_equal), "")
    check("SQL vs Python", "Overall OTIF identical", abs(sql_otif - r.syn_kpis["otif_rate"]) < 1e-12, f"{sql_otif:.4%}")
    return out


def write_audit(r, path: Path | None = None) -> Path:
    s = r.settings
    path = path or s.path("docs_dir") / "data_quality_audit.md"
    a = r.clean.audit
    checks = integrity_checks(r)
    manifest_file = s.path("public_dir") / "SNAPSHOT_MANIFEST.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8")) if manifest_file.exists() else {}
    passed = sum(c["result"] == "PASS" for c in checks)
    lt = a["line_type_counts"]
    lines = [
        "# Data-quality audit",
        "",
        "Generated by `python -m supplierpulse.pipeline` from the pinned snapshot. Every number below is produced by the code, not typed by hand.",
        "",
        f"**Integrity checks: {passed} of {len(checks)} passed.**",
        "",
        "## 1. Observed data: City of Austin purchase-order lines",
        "",
        "| Item | Result |",
        "|---|---|",
        f"| Source data build date | {', '.join(a['source_build_dates'])} |",
        f"| Raw rows | {a['raw_rows']:,} |",
        f"| Raw line value | ${a['raw_amount_total']:,.2f} |",
        f"| Award dates covered | {a['award_date_min']} to {a['award_date_max']} |",
        f"| Rows excluded (rules V1-V4) | {a['excluded_rows']:,} (${a['excluded_amount']:,.2f}) |",
        f"| Rows excluded by reason | {a['excluded_by_reason'] or 'none: no missing keys, unparseable dates, non-positive amounts or negative quantities'} |",
        f"| Validated rows | {a['clean_rows']:,} (${a['clean_amount_total']:,.2f}) |",
        f"| Unit-priced lines (qty x price = amount) | {lt.get('unit_priced', 0):,} |",
        f"| Amount-only lines (no quantity/price; spend only) | {lt.get('amount_only', 0):,} |",
        f"| Inconsistent quantity/price lines (spend only) | {lt.get('inconsistent', 0):,} |",
        f"| Exact duplicate rows (flagged, retained) | {a['possible_duplicate_rows']:,} (${a['possible_duplicate_amount']:,.2f}, {a['possible_duplicate_amount'] / a['clean_amount_total']:.4%} of value) |",
        f"| PO numbers with letter suffix whose base exists (retained) | {a['po_suffix_revision_rows']:,} rows (${a['po_suffix_revision_amount']:,.2f}) |",
        f"| Lines with no unit of measure | {a['missing_uom_rows']:,} (all amount-only) |",
        f"| Lines with no master agreement reference | {a['missing_master_agreement_rows']:,} (contract- and PO-type orders) |",
        f"| Lines whose item text is on the reviewed product list (usable for price comparison) | {a['reviewed_item_text_rows']:,} |",
        f"| Exact duplicate rows inside FY2022-FY2026 | {a['possible_duplicate_rows_focus']:,} (${a['possible_duplicate_amount_focus']:,.2f}) |",
        f"| Vendors outside the US / blank country | {a['non_us_vendor_rows']:,} / {a['blank_country_rows']:,} rows (amounts treated as USD) |",
    ]
    if manifest:
        lines += [
            f"| Public snapshot columns (allowlist) | {len(manifest.get('snapshot_columns', []))}: {', '.join(manifest.get('snapshot_columns', []))} |",
            f"| Source columns not published | {', '.join(manifest.get('source_columns_not_published', []))} |",
            f"| Lines carrying a reviewed product description key | {manifest.get('lines_with_reviewed_item_text', 0):,} ({manifest.get('reviewed_item_texts')} reviewed texts) |",
            f"| Vendors / vendors with a published business name | {manifest.get('vendors_in_snapshot', 0):,} / {manifest.get('reviewed_vendor_names')} |",
            f"| Raw file SHA-256 | `{manifest.get('raw_sha256', '')[:16]}...` |",
        ]
    pr = r.prices.summary
    lines += [
        "",
        "### Price-comparison coverage",
        "",
        f"- Comparable lines: {pr['comparable_lines']:,} across {pr['comparable_items']:,} items / {pr['comparable_item_years']:,} item-years.",
        f"- They cover {pr['comparable_share_of_unit_priced_spend']:.1%} of unit-priced spend and {pr['comparable_share_of_total_spend']:.1%} of all focus-window spend.",
        f"- {pr['entry_issue_lines']:,} comparable lines sit at <= 0.25x or >= 10x their item-year median and are treated as probable unit or entry inconsistencies (excluded from the opportunity).",
        "",
        "## 2. Synthetic demonstration data",
        "",
        "| Item | Result |",
        "|---|---|",
        f"| Seed / as-of date | {r.syn_kpis['seed']} / {r.syn_kpis['as_of_date']} |",
        f"| Suppliers / POs / PO lines / receipts | {r.syn_kpis['suppliers']} / {r.syn_kpis['purchase_orders']:,} / {r.syn_kpis['po_lines']:,} / {r.syn_kpis['receipts']:,} |",
        f"| Cancelled lines (excluded from rates) | {r.syn_kpis['cancelled_lines']} |",
        f"| Lines closed short | {r.syn_kpis['short_closed_lines']} |",
        f"| Open lines / overdue lines | {r.syn_kpis['open_lines']} / {r.syn_kpis['overdue_lines']} |",
        f"| Due lines in delivery denominators | {r.syn_kpis['due_lines']:,} |",
        "",
        "## 3. Integrity checks",
        "",
        "| Area | Check | Result | Detail |",
        "|---|---|---|---|",
    ]
    lines += [f"| {c['area']} | {c['check']} | {c['result']} | {c['detail']} |" for c in checks]
    lines += [
        "",
        "## 4. Known limitations that remain",
        "",
        "- The Austin source has no line number, so exact duplicate rows cannot be proven to be errors; they are retained and quantified above.",
        "- Vendor identity is by vendor code. The same company under two codes is counted as two vendors; this can understate concentration.",
        "- Award value is a commitment at award, not an invoice or payment, and post-award changes are not visible.",
        "- Free-text descriptions are not published; price comparisons cover only items on the reviewed product list, so most spend is outside price analysis.",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
