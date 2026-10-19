# Synthetic demonstration data

**Everything in this dataset is invented.** It exists because the public procurement data used in Part A has no promised dates or goods receipts, so supplier delivery performance cannot be measured from it.

## Generation

- Code: [`src/supplierpulse/synthetic.py`](../src/supplierpulse/synthetic.py). The seed is fixed (`20261015` in `config/settings.toml`), so every run produces identical data (a test checks this).
- Window: orders 1 Oct 2024 – 30 Sep 2026, measured as of 30 Sep 2026.
- Volume: 2,600 POs, 4,837 PO lines (1–4 per PO), 4,841 goods receipts, 14 suppliers, 6 categories, 46 items.
- Published as CSV in [`data/public/synthetic/`](../data/public/synthetic/). Every row carries `data_origin = SYNTHETIC`.
- Supplier IDs `SUP-01` … `SUP-14`, names "Synthetic Supplier NN". No synthetic supplier is derived from, or named after, a real vendor.

## How each line is simulated

1. **Quoted lead time:** fixed per supplier and category, set so that the supplier's designed on-time probability holds in year 1. Promised date = order date + quoted lead time.
2. **Actual lead time:** drawn from a normal distribution around the supplier's true mean and spread. In year 2 the mean and spread can shift, which is how deterioration is designed.
3. **Backorders:** some profiles add a 15–150 day delay with a small probability, creating aged overdue lines.
4. **Partial shipments:** with the profile's probability, the first receipt carries 40–80% of the quantity; the rest arrives 5–20 days later, or never (closed short 30 days after the promised date).
5. **Receipts after the as-of date** are not recorded, so recent lines stay open.
6. **Cancellations:** 2% of lines are cancelled within 5 days of ordering, with no receipts.
7. **Quality:** each receipt has a profile-specific chance of a rejection of 5–30% of its quantity.
8. **Price:** paid price = contract (standard) price × the supplier's price factor × noise (σ = 3%).

## Designed supplier behaviour

These patterns are **inputs to the simulation**, so the dashboard showing them demonstrates that the method detects them, not that they exist anywhere real.

| Supplier | Category | Designed behaviour |
|---|---|---|
| SUP-01 | Electrical | Largest electrical supplier; on-time probability falls from 93% to 68% in year 2 with longer, more variable lead times and backorders |
| SUP-02 | Electrical | Reliable alternative |
| SUP-03 | Electrical | Only 6 POs: tests the insufficient-evidence rule |
| SUP-04 | Fleet | Chronically late, highly variable lead times, occasional backorders |
| SUP-05 | Fleet | Reliable |
| SUP-14 | Fleet | Mid-performing, occasional quality issues |
| SUP-06 | MRO | Excellent, large category share |
| SUP-07 | MRO | Frequent split and short shipments |
| SUP-08 | MRO + PPE | Generalist |
| SUP-09 | Water chemicals | Sole source, good performance (dependency without a performance problem) |
| SUP-10 | PPE | Low price, recurring quality rejections |
| SUP-11 | PPE | Reliable |
| SUP-12 | IT | Paid prices about 13% above contract |
| SUP-13 | IT | Good, but only 10 POs: tests the provisional (not ranked) rule |

## Limits

The magnitudes ($9.2M of spend over two years, $150 per late line) are illustrative. The value of Part B is the **method**: line-level definitions, denominators, partial-receipt handling, evidence thresholds and the separation of performance from dependency. Those transfer directly to a real ERP extract with PO lines and goods receipts.
