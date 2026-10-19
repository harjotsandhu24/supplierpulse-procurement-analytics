"""Shared documentation text (data dictionary) used by the workbook and docs/data_dictionary.md."""

# (table or sheet, field, origin O/S/D, definition)
DATA_DICTIONARY = [
    ("obs_po_line", "line_id", "D", "Sequential ID assigned after validation (one row per validated source line)."),
    ("obs_po_line", "source_row", "O", "Row number in the downloaded source file, for audit back to the source."),
    ("obs_po_line", "purchase_order", "O", "City purchase-order number (PURCHASE_ORDER). Prefix DO = delivery order against a master agreement; CT = contract-type order; PO = standalone purchase order."),
    ("obs_po_line", "award_date", "O", "Award date of the purchase order (AWARD_DATE). Not a delivery or receipt date."),
    ("obs_po_line", "fiscal_year", "D", "City of Austin fiscal year (1 Oct - 30 Sep), e.g. FY2026 = Oct 2025 - Sep 2026."),
    ("obs_po_line", "vendor_code", "D", "Pseudonymous vendor ID: 'V' + first 10 hex characters of SHA-256 of the City vendor code. The vendor key."),
    ("obs_vendor", "vendor_name", "D", "Business name from the reviewed list (config/reviewed_vendor_names.csv); otherwise 'Vendor <ID>' (name not published)."),
    ("obs_po_line", "commodity_code", "O", "NIGP / COA commodity code (COMMODITY). 11-digit codes identify specific inventory items."),
    ("obs_po_line", "nigp_class", "D", "First three digits of the commodity code (NIGP class)."),
    ("obs_category", "class_label", "D", "Class title from the source's own 3-digit rows, or the most common item description in the class."),
    ("obs_category", "spend_family", "D", "Analyst grouping of NIGP classes (config/category_families.toml)."),
    ("obs_po_line", "item_text_key", "D", "SHA-256 of the normalised item text, present only when that text is on the reviewed product list; empty otherwise."),
    ("obs_po_line", "item_description", "D", "Reviewer-cleaned public label for a reviewed product specification; empty for all other lines."),
    ("obs_po_line", "item_specific", "D", "True when the line's item text is on the reviewed product list; required for price comparison."),
    ("obs_po_line", "uom", "O", "Unit of measure (UNIT_OF_MEASURE), normalised. Blank on amount-only lines."),
    ("obs_po_line", "quantity / unit_price", "O", "Ordered quantity and unit price. Both zero on amount-only lines."),
    ("obs_po_line", "line_amount", "O", "Line total in USD (ITM_TOT_AM): awarded value, used as 'spend'. Not an invoice or payment."),
    ("obs_po_line", "line_type", "D", "unit_priced (qty x price reconciles to amount), amount_only (no qty/price) or inconsistent."),
    ("obs_po_line", "has_master_agreement", "D", "True when the source line references a master agreement (all DO orders; no CT or PO orders). The agreement number itself is not published."),
    ("obs_po_line", "possible_duplicate", "D", "True for the 2nd+ copy of a row identical on all 21 source columns (detected before columns were dropped; flagged, not removed)."),
    ("obs_po_line", "po_suffix_revision", "D", "PO number ends in letters and its base number also exists (possible follow-on order; retained)."),
    ("syn_po_line", "promised_date", "S", "Supplier-committed delivery date for the line (order date + quoted lead time)."),
    ("syn_po_line", "cancelled", "S", "Line cancelled before any receipt; excluded from delivery, quality and spend metrics."),
    ("syn_po_line", "short_closed", "S", "Line closed by the buyer with less than the ordered quantity received."),
    ("syn_goods_receipt", "received_qty / rejected_qty", "S", "Quantity received on a goods receipt and the quantity rejected at inspection."),
    ("Syn_Lines", "due", "D", "1 if not cancelled and promised on/before the as-of date. Only due lines enter delivery rates."),
    ("Syn_Lines", "on_time", "D", "1 if a due line had a receipt on/before promised date + grace days."),
    ("Syn_Lines", "in_full", "D", "1 if a due line's total received quantity reached the ordered quantity (less tolerance)."),
    ("Syn_Lines", "otif", "D", "1 if the quantity received by the promised date + grace reached the ordered quantity. Unreceived due lines are 0."),
    ("Syn_Lines", "qty_by_promise", "D", "Quantity received on or before promised date + grace."),
    ("Syn_Lines", "completion_date", "D", "Receipt date when cumulative quantity first reached the ordered quantity; blank if never."),
    ("Syn_Lines", "days_late", "D", "Completed: completion - promised; short-closed: last receipt - promised; open: as-of - promised; floored at 0; due lines only."),
    ("Syn_Lines", "lead_time_days", "D", "Order date to completion date, completed lines only."),
    ("Syn_Lines", "open / overdue", "D", "Open = not cancelled, not short-closed, not complete. Overdue = open and promised before the as-of date."),
    ("Syn_Lines", "due_period", "D", "prior_12m or last_12m relative to the as-of date, by promised date."),
    ("Supplier_Summary", "reject_rate", "D", "Rejected quantity / received quantity (non-cancelled lines)."),
    ("Supplier_Summary", "ppv_pct", "D", "Ordered value at paid prices / ordered value at contract (standard) prices - 1."),
    ("Scorecard", "performance_score", "D", "Weighted average of 0-100 component scores (OTIF 40%, quality 25%, lead-time consistency 20%, lateness 15%), re-weighted when a component is missing."),
    ("Scorecard", "evidence_status", "D", "Ranked (>= 30 due lines), Provisional (10-29) or Insufficient evidence (< 10, not scored)."),
    ("Dependency", "dependency_risk", "D", "High: sole supplier in category, >= 60% of category spend, or >= 15% of total; Medium: >= 35% / >= 8%; else Low."),
    ("Austin_Categories", "HHI", "D", "Herfindahl-Hirschman Index of vendor shares in the class (0-10,000); >= 2,500 = highly concentrated."),
    ("Austin_Prices", "item-year median", "D", "Median unit price of the same commodity code + unit + description in the same fiscal year (>= 4 purchases)."),
]


def write_data_dictionary(path) -> None:
    """Render DATA_DICTIONARY as docs/data_dictionary.md."""
    lines = [
        "# Data dictionary",
        "",
        "Generated from `src/supplierpulse/docs_text.py`. Origin: **O** = observed City of Austin field, "
        "**S** = synthetic field, **D** = derived by this project.",
        "",
        "| Table / sheet | Field | Origin | Definition |",
        "|---|---|---|---|",
    ]
    lines += [f"| {t} | `{f}` | {o} | {d} |" for t, f, o, d in DATA_DICTIONARY]
    lines += ["", "Full SQL table list: [sql/README.md](../sql/README.md). Metric definitions: [methodology.md](methodology.md).", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
