# Data sources, provenance and licensing

## Selected source (observed data)

| Item | Detail |
|---|---|
| Dataset | *Purchase Order Quantity Price detail for Commodity/Goods procurements* |
| Publisher | City of Austin, Texas: Austin Financial Services, via the official open data portal |
| Landing page | https://data.austintexas.gov/d/3ebq-e9iz |
| Download used | https://data.austintexas.gov/api/views/3ebq-e9iz/rows.csv?accessType=DOWNLOAD |
| Downloaded | 15 Oct 2026; source `DATA_BUILD_DATE` 10/05/2026 |
| Size | 321,683 rows, 21 columns, ~98 MB CSV; SHA-256 recorded in [`data/public/SNAPSHOT_MANIFEST.json`](../data/public/SNAPSHOT_MANIFEST.json) |
| Observation period | Award dates 1 Oct 2009 – 30 Sep 2026 (FY2010–FY2026) |
| Content | Goods PO lines: commodity code and description, quantity, unit, unit price, line total, master agreement, contract name, PO number, award date, vendor code, name and address |
| Not included | Promised dates, receipt/delivery dates, returns, quality, invoices, payments, cancellations after award. Certain Austin Energy transactions are excluded by the City (Texas Government Code §552.133) |
| Terms | [City of Austin Open Data Terms of Use](https://data.austintexas.gov/d/2z87-8uh7): data available through the portal "is offered free and without restriction". Attribution is requested but not required. The City "cannot vouch for any analyses conducted with data retrieved" from the portal |
| Redistribution | Permitted by the terms. The repository nevertheless publishes only a minimal-column derived snapshot (below), never the original file |

### Public snapshot: what is published and why

The original CSV contains free text that names City staff, phone numbers, e-mail addresses, a private resident's address and an employee eyeglasses purchase with an employee ID. Pattern-based redaction missed some of these, so the published snapshot is built from an **allowlist of analytical columns** instead.

| Item | Detail |
|---|---|
| File | `data/public/austin_po_lines_snapshot.parquet` (6.7 MB, 321,683 rows, one per source row) |
| Built from | Source CSV built by the City on 5 Oct 2026, downloaded 15 Oct 2026; raw-file SHA-256 in `SNAPSHOT_MANIFEST.json` |
| Columns published | `SOURCE_ROW`, `PURCHASE_ORDER`, `AWARD_DATE`, `VENDOR_ID`, `VENDOR_COUNTRY`, `COMMODITY`, `QUANTITY`, `UNIT_OF_MEASURE`, `UNIT_PRICE`, `ITM_TOT_AM`, `HAS_MASTER_AGREEMENT`, `ITEM_TEXT_KEY`, `RAW_EXACT_DUPLICATE`, `DATA_BUILD_DATE` |
| Not published | `LGL_NM` (vendor name), `AD_LN_1`, `AD_LN_2`, `CITY`, `ST`, `ZIP` (address), `EXTENDED_DESCRIPTION`, `CONTRACT_NAME`, `COMMODITY_DESCRIPTION`, `UNIT_OF_MEAS_DESC`, `MASTER_AGREEMENT` (number), `VENDOR_CODE` |
| Transformations | `VENDOR_ID` = "V" + first 10 hex characters of SHA-256(vendor code). `HAS_MASTER_AGREEMENT` = whether an agreement number was present. `ITEM_TEXT_KEY` = SHA-256 of the normalised item text, **only** when that text is on the reviewed product list; empty otherwise. `RAW_EXACT_DUPLICATE` is computed on all 21 source columns before any column is dropped |
| Vendor names | Published separately for 170 reviewed business vendors ([`config/reviewed_vendor_names.csv`](../config/reviewed_vendor_names.csv)): the top 150 by spend plus the largest vendor in every category over $1M. Two vendors that appear to be individuals are withheld. All 1,700+ other vendors appear only as pseudonymous IDs |
| Item descriptions | 153 reviewer-cleaned product labels ([`config/reviewed_item_texts.csv`](../config/reviewed_item_texts.csv)), out of 267 candidate texts that could form like-for-like price groups. Excluded: personal names, addresses, contact details, invoice instructions, quote/bid/PO references, embedded prices, site or delivery notes, service descriptions and vague text. Internal stock-review notes (which contained staff initials) were cut from the labels |
| Category labels | `data/public/nigp_class_labels.csv`: 211 NIGP class titles from the City's commodity taxonomy (reviewed; product categories only) |
| Limitations | Price analysis covers only reviewed items (about 5% of spend). Category labels are the City's taxonomy text. Award values only; no invoices, payments, deliveries or post-award cancellations |

The original file stays in `data/raw/` (git-ignored). Privacy checks and results: [privacy_review.md](privacy_review.md).

## Candidate datasets evaluated

| Candidate | Strengths | Why not selected |
|---|---|---|
| **USAID Supply Chain Shipment Pricing Data** (SCMS, ~10k shipments, 2006–2015) | Has *scheduled* and *delivered-to-client* dates, so it could support real delivery metrics | `data.usaid.gov` no longer resolves (checked 15 Oct 2026), so there is no reproducible official download. The metadata licence conflicts (CC BY-ND 4.0 vs "CC-BY"; no-derivatives would restrict publishing derived tables). The publisher warns that lead-time conclusions "will not be accurate". Mirrors exist on third-party sites, but provenance and terms could not be verified |
| USAID GHSC-PSM Health Commodity Delivery dataset | Delivery-oriented | Same portal shutdown; catalogue record returned 404 |
| City of Chicago Contracts | Large, well-known | Contract awards and PO headers, no line-level quantities, unit prices or delivery dates |
| East Baton Rouge Purchase Orders and Contracts | PO line detail | Smaller; no delivery dates |
| **City of Austin PO Quantity Price detail** | Official publisher, explicit permissive terms, line-level quantity, unit and unit price, vendor codes, commodity codes, 17 years, refreshed weekly | **Selected.** No delivery data, so it is used only for metrics it supports |

## Consequence: two-part design

No candidate combined **verifiable redistribution rights** with **real promised and receipt dates**. As the project brief directs, SupplierPulse therefore uses:

- **Part A, observed:** City of Austin data for spend, concentration, agreement coverage and like-for-like price analysis.
- **Part B, synthetic:** a deterministic order, receipt and quality dataset ([synthetic_data.md](synthetic_data.md)) to demonstrate delivery performance, OTIF, scorecards and order management.

No delivery metric is ever calculated for a real vendor, and no synthetic result is attached to a real vendor.

## Attribution

> Data retrieved from Data.AustinTexas.gov (https://data.austintexas.gov), dataset 3ebq-e9iz, City of Austin, Texas.
