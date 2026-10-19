# SQL analysis package

DuckDB SQL over the analytical database built by `python -m supplierpulse.pipeline` (`data/processed/supplierpulse.duckdb`, rebuilt each run). Results from the latest run are saved in [`outputs/sql_results/`](../outputs/sql_results/). Run the queries alone with `python -m supplierpulse.database`.

Every query starts with its business question and data origin. Tests in [`tests/test_sql.py`](../tests/test_sql.py) run all 12 queries and require their results to match the pandas pipeline.

## Tables

| Table | Grain | Origin |
|---|---|---|
| `obs_po_line` | one validated City of Austin PO line (spend lives only here) | Observed |
| `obs_po_header` | one PO (aggregated from lines) | Observed |
| `obs_vendor` | one vendor code | Observed |
| `obs_category` | one NIGP 3-digit class, with label and spend family | Observed / analyst grouping |
| `obs_excluded_line` | rows rejected by validation, with reason | Observed |
| `syn_supplier`, `syn_category`, `syn_item` | synthetic master data | Synthetic |
| `syn_purchase_order`, `syn_po_line` | synthetic orders and lines (promised date, cancellation, short-close) | Synthetic |
| `syn_goods_receipt` | synthetic receipts with received and rejected quantity | Synthetic |
| `params` | as-of date, tolerances, thresholds and scorecard weights from config | Config |

## Views ([`views/`](views/))

| View | Purpose |
|---|---|
| `v_obs_focus_line` | Focus-window lines with vendor name, class label and family (many-to-one joins, no row inflation) |
| `v_syn_line_delivery` | One row per synthetic PO line: due, on-time, in-full, OTIF, completion date, days late, lead time, open/overdue. Computed from receipts with window functions |
| `v_syn_supplier_scorecard` | Weighted 0–100 score with re-weighting for missing components, evidence status and competition rank |

## Queries ([`queries/`](queries/))

| # | Business question | Demonstrates | Data |
|---|---|---|---|
| 01 | Which vendors receive the most spend? | Window functions, running share, deterministic tie-break | Observed |
| 02 | How concentrated is spend across vendors? | HHI, top-N share, vendors-for-80% | Observed |
| 03 | How has spend in each family changed by year? | `LAG` year-over-year change, share of year | Observed |
| 04 | Where does one vendor dominate a category? | Per-category ranking, HHI, rule flags from `params` | Observed |
| 05 | How much spend uses master agreements, and where is standalone buying recurring? | Coverage by order type, `HAVING` screen | Observed |
| 06 | Where do we pay different prices for the same item in the same year? | Like-for-like grouping, windowed `MEDIAN`, outlier handling | Observed |
| 07 | Which suppliers deliver on time and in full? | Correct denominators (due lines only), unreceived = failure | Synthetic |
| 08 | Whose lead times are unpredictable? | `STDDEV_SAMP`, `QUANTILE_CONT` on completed lines | Synthetic |
| 09 | Which open PO lines are overdue? | Open-order backlog and ageing | Synthetic |
| 10 | How do suppliers rank on the scorecard? | Weighted scoring, evidence thresholds, `RANK()` ties | Synthetic |
| 11 | Whose performance is deteriorating? | Period comparison with conditional aggregation | Synthetic |
| 12 | Which suppliers combine weak performance with high dependency? | Separating performance from dependency; action quadrant | Synthetic |

## Notes on correctness

- Spend is summed only from `obs_po_line`; headers are never joined back to lines.
- Delivery rates use `FILTER (WHERE due)`, so cancelled and not-yet-due lines never enter a denominator.
- A due line with no receipts has `NULL` receipt fields, so its on-time/in-full/OTIF flags evaluate to false, never true.
- Query 06 compares prices only within the same commodity code, unit, description and fiscal year.
