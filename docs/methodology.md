# Methodology

This document defines every metric, rule and assumption behind SupplierPulse. All thresholds live in [`config/settings.toml`](../config/settings.toml); changing one and re-running the pipeline updates every output.

## 1. Evidence labels

| Label | Meaning | Used for |
|---|---|---|
| **Observed** | Real City of Austin purchase-order records | Spend, vendor and category concentration, agreement coverage, like-for-like prices |
| **Synthetic** | Deterministic, generated demonstration data with anonymous suppliers | Delivery (OT, IF, OTIF), lead time, quality, open/overdue orders, scorecard, reallocation scenario |
| **Modelled** | A calculation under stated assumptions | Price-harmonisation opportunity, scenario benefits |
| **Assumed** | An input chosen by the analyst | Cost per late line ($150), scorecard targets and weights, category families, USD currency |

The two data sources are never joined. Synthetic suppliers use codes (`SUP-01`) and names ("Synthetic Supplier 01") that cannot be confused with real vendors (a test checks this).

## 2. Observed data: City of Austin

### 2.1 Reporting period

- **Focus window: FY2022–FY2026** (1 Oct 2021 – 30 Sep 2026). These are five complete City fiscal years; the source build date is 5 Oct 2026, so FY2026 is complete.
- **History: FY2010–FY2026**, used only for the spend-by-year trend.
- Fiscal year = calendar year of the award date + 1 if the month is October or later.

### 2.2 Validation rules (src/supplierpulse/validate.py)

| Rule | Treatment | Result on snapshot |
|---|---|---|
| V1 required fields present | exclude, logged | 0 rows |
| V2 award date parses and is not after the build date | exclude, logged | 0 rows |
| V3 line amount numeric and > 0 | exclude, logged | 0 rows |
| V4 quantity / unit price numeric and non-negative | exclude, logged | 0 rows |
| V5 line type: `unit_priced` (qty × price reconciles to amount within 0.5% or $0.01), `amount_only` (qty = price = 0), `inconsistent` | all retained for spend; only `unit_priced` used for prices | 212,293 / 109,390 / 0 |
| V6 exact duplicate rows (all 21 source columns) | flagged, retained (no line number in source); excluded from price comparisons | 82 rows, $316,070 (9 rows, $16,385 in FY2022–FY2026); conclusions unchanged when excluded ([analytical_audit.md](analytical_audit.md)) |
| V7 PO number with letter suffix whose base exists | flagged, retained (each carries its own amounts) | 380 rows |
| V8 currency not stated | treated as USD (assumption) | 474 non-US vendor rows |
| V9 item text on the reviewed product list | required for price comparison | 153 reviewed texts |

Validated + excluded rows and dollars reconcile exactly to the raw file (see [data_quality_audit.md](data_quality_audit.md)).

### 2.3 Data model and double-counting controls

- `fact_po_line` is the only table that carries spend. `fact_po_header` is aggregated from lines and never re-joined to them.
- `dim_vendor` (one row per pseudonymous vendor ID; business name only if on the reviewed list) and `dim_category` (one row per NIGP class) are joined many-to-one with pandas `validate="many_to_one"`. The build fails if row count or total spend changes.
- Every PO is checked to have exactly one vendor and one award date.

### 2.4 Spend and concentration

- **Spend** = awarded PO line value (`ITM_TOT_AM`). It is a commitment at award, not an invoice or payment.
- **Share** = vendor (or category) spend / focus-window spend.
- **HHI** = Σ (percentage share)², 0–10,000. ≥ 2,500 = "highly concentrated" (US DOJ/FTC threshold).
- **Vendors for 80%** = the number of vendors, ranked by spend, needed for cumulative share to reach 80%. Pareto class A/B/C uses cumulative share *before* the vendor (< 80%, < 95%, rest). Ties are ordered by vendor code.
- **Category** = NIGP 3-digit class (first three digits of the commodity code). Labels come from the source's own 3-digit rows, or else the most common item description. **Spend families** are an analyst grouping in [`config/category_families.toml`](../config/category_families.toml).

### 2.5 Exception rules (observed)

| Rule | Definition |
|---|---|
| R1 Single-vendor concentration (exposure to review) | Class spend ≥ $1M and top vendor share ≥ 90%. Tagged *recurring* if the top vendor had ≥ 12 orders across ≥ 3 fiscal years, otherwise *few large orders* (e.g. one-off project buys) |
| R2 Highly concentrated category | Class spend ≥ $1M and HHI ≥ 2,500 (not already R1) |
| R3 Vendor dependency | Vendor ≥ 5% of total focus-window spend |
| R4 Recurring purchasing outside master agreements | Class with ≥ 10 standalone (CT- or PO-type) orders totalling ≥ $250k. In this source every DO references a master agreement and no CT/PO order does |
| R5 Price above item-year baseline | Comparable line ≥ 1.5× its item-year median |
| R6 Unusual year-over-year price increase | Comparable item's median rose ≥ 25% between consecutive fiscal years |

### 2.6 Like-for-like price variance

A price is compared only with prices for **the same item**:

1. same full commodity code, same unit of measure, and same full item text, where that text must be on the human-reviewed list of genuine product specifications (`config/reviewed_item_texts.csv`);
2. **same fiscal year** (so inflation across years is not read as variance);
3. only `unit_priced` lines and no flagged duplicates;
4. at least 4 purchases in the item-year.

Baseline = item-year **median**. Lines ≤ 0.25× or ≥ 10× the median are treated as probable unit or entry inconsistencies and excluded from the opportunity. **Modelled harmonisation opportunity** = Σ (price − median) × quantity on lines ≥ 1.5× median. This covers 154 items and about 4.7% of spend. With a quantity control (only lines within 0.5×–2× of the item-year median quantity), the excess falls from $4.8M to $2.0M, so part of the dispersion may reflect order size. It is an opportunity to investigate, not a saving. Transformer price increases hold with order size controlled (median +34%).

## 3. Synthetic delivery data

Why it exists and how it was designed: [synthetic_data.md](synthetic_data.md).

### 3.1 Unit of measurement

Delivery performance is measured **per purchase-order line** at the as-of date (30 Sep 2026).

| Metric | Definition |
|---|---|
| Due line | Not cancelled and promised date ≤ as-of date. **Only due lines enter rate denominators.** |
| On time (OT) | A receipt on or before promised date + grace (0 days) |
| In full (IF) | Total received quantity ≥ ordered quantity × (1 − tolerance), tolerance 0% |
| OTIF | Quantity received **by the promised date** ≥ ordered quantity × (1 − tolerance) |
| No receipts | A due line with no receipts is **not** OT, IF or OTIF. Missing receipts never count as success |
| Completion date | Receipt date when cumulative quantity first reaches the ordered quantity |
| Days late | Completed: completion − promised; closed short: last receipt − promised; open: as-of − promised; floored at 0 |
| Lead time | Order date → completion date, completed lines only. Variability = sample standard deviation (days) |
| Open / overdue | Open = not cancelled, not closed short, not complete. Overdue = open and promised before the as-of date |
| Cancelled | Excluded from delivery, quality and spend; counted separately |
| Closed short | Buyer closed the line with less than ordered; it fails IF/OTIF but is not open |
| Reject rate | Rejected quantity / received quantity |
| PPV | Ordered value at paid prices / ordered value at contract price − 1 |

### 3.2 Scorecard (src/supplierpulse/scoring.py, sql/views/03)

Each component is scaled linearly from 0 points (poor) to 100 points (target) and clipped:

| Component | Weight | Poor (0) | Target (100) |
|---|---|---|---|
| OTIF rate | 40% | 70% | 95% |
| Reject rate | 25% | 5% | 0.5% |
| Lead-time standard deviation | 20% | 7 days | 2 days |
| Average days late (all due lines) | 15% | 5 days | 0 days |

- **Missing data is not scored as poor.** If a component cannot be measured (e.g. fewer than 20 completed lines for lead-time variability), it is dropped and the remaining weights are re-normalised. The row is flagged `reweighted`.
- **Evidence rule:** ≥ 30 due lines = *Ranked*; 10–29 = *Provisional* (shown, not ranked); < 10 = *Insufficient evidence* (no score).
- **Ranking:** competition ranking on the score rounded to 0.1. Equal scores share a rank, and the next rank skips.
- **Tiers:** Preferred ≥ 85, Acceptable ≥ 70, Improvement needed ≥ 55, otherwise At risk.

### 3.3 Dependency risk (kept separate from performance)

High = sole supplier in a category, or ≥ 60% of a category's spend, or ≥ 15% of total spend. Medium = ≥ 35% of a category or ≥ 8% of total. **Action quadrant** combines the two: *Critical: act now* (High dependency, score < 70), *Strategic: protect and monitor* (High, ≥ 70), *Develop or replace* (not High, < 70), *Maintain*.

### 3.4 Exception rules (synthetic)

S1 OTIF < 80% (≥ 30 due lines) · S2 OTIF fell ≥ 10 points, prior vs last 12 months (≥ 30 due lines in each) · S3 lead-time SD ≥ 5 days (≥ 20 completed lines) · S4 in-full < 90% · S5 reject rate ≥ 2% · S6 PPV ≥ 10% · S7 overdue open line · S8 high dependency.

## 4. Recommendations and priority

Actions are generated from the exception register by fixed rules (see the docstring of `src/supplierpulse/recommendations.py`). Each action states its supporting metric, business significance, recommended action, data limitation and source exception IDs. Priority is High, Medium or Low by explicit thresholds; for example, a recurring single-vendor category with ≥ $10M of spend is High.

## 5. Scenarios (all modelled)

- **Volume reallocation (synthetic).** Moving share *x* of a supplier's last-12-month volume to an alternative supplier gives `late lines avoided = x · L_from · (OTIF_to − OTIF_from)`. Handling cost uses an **assumed $150 per late line**. Price impact = moved spend × ((1 + PPV_to)/(1 + PPV_from) − 1). The model assumes the alternative keeps its OTIF and prices at higher volume, so capacity must be confirmed first.
- **OTIF to target (synthetic).** Late lines avoided if a supplier reached 95% OTIF on its last-12-month volume.
- **Price harmonisation (observed).** The modelled opportunity at 25%, 50% and 100% capture.

The same formulas run in Python and live in the Excel `Scenario` sheet. Tests check both against a closed form.

## 6. Validation approach

- 74 automated tests, covering hand-built edge cases for partial receipts, cancellations, missing receipts, ties, small samples, unit control, duplicate joins and privacy.
- SQL views recompute delivery metrics and the scorecard independently of pandas; tests require identical results.
- The workbook is recalculated by an independent formula engine; all 55 `Validation` rows must match Python.
- The data-quality audit runs 27 integrity checks on every pipeline run.
- An independent script (`scripts/independent_audit.py`) recomputes the headline findings from the raw source with separate SQL code; all 17 values match ([analytical_audit.md](analytical_audit.md)).
- A privacy scan checks every publishable file against private values taken from the raw source ([privacy_review.md](privacy_review.md)).
