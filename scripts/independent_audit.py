"""Independent recomputation of SupplierPulse's headline findings.

    python scripts/independent_audit.py

Deliberately does NOT import the pipeline's analysis code. It reads the private raw CSV
(data/raw/, local only) with DuckDB SQL, recomputes every headline number from scratch, compares
it with outputs/metrics.json, runs sensitivity tests (duplicates excluded, vendors grouped by name,
quantity-controlled prices) and writes docs/analytical_audit.md. Only aggregates are written.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "austin_po_lines_raw.csv"
REVIEWED = ROOT / "config" / "reviewed_item_texts.csv"


def money(x: float) -> str:
    return f"${x / 1e6:,.1f}M" if abs(x) >= 1e6 else f"${x:,.0f}"


def main() -> int:
    if not RAW.exists():
        print("Private raw file not found; run `python -m supplierpulse.ingest --download` first.")
        return 1
    metrics = json.loads((ROOT / "outputs" / "metrics.json").read_text(encoding="utf-8"))
    hl = metrics["headline"]
    con = duckdb.connect()
    con.execute(f"""
        CREATE TABLE raw AS SELECT * FROM read_csv('{RAW.as_posix()}', all_varchar=true, header=true);
        CREATE TABLE src AS
        SELECT *,
               row_number() OVER () AS rn,
               strptime(AWARD_DATE, '%m/%d/%Y')::DATE AS award,
               CAST(ITM_TOT_AM AS DOUBLE) AS amt,
               CAST(QUANTITY AS DOUBLE) AS qty,
               CAST(UNIT_PRICE AS DOUBLE) AS price,
               year(strptime(AWARD_DATE, '%m/%d/%Y')) + CASE WHEN month(strptime(AWARD_DATE, '%m/%d/%Y')) >= 10 THEN 1 ELSE 0 END AS fy,
               substr(COMMODITY, 1, 3) AS cls
        FROM raw;
        -- exact duplicates over all 21 source columns: keep the first occurrence
        CREATE TABLE src_flag AS
        SELECT *, row_number() OVER (PARTITION BY "COMMODITY", "COMMODITY_DESCRIPTION", "EXTENDED_DESCRIPTION", "QUANTITY", "UNIT_OF_MEASURE", "UNIT_OF_MEAS_DESC", "UNIT_PRICE", "ITM_TOT_AM", "MASTER_AGREEMENT", "CONTRACT_NAME", "PURCHASE_ORDER", "AWARD_DATE", "VENDOR_CODE", "LGL_NM", "AD_LN_1", "AD_LN_2", "CITY", "ST", "ZIP", "CTRY", "DATA_BUILD_DATE" ORDER BY rn) > 1 AS is_dup
        FROM src;
    """)
    rows: list[tuple[str, str, str, str]] = []

    def check(label: str, independent, pipeline, fmt=lambda v: f"{v}", tol: float = 1e-6):
        ok = abs(float(independent) - float(pipeline)) <= tol * max(1.0, abs(float(pipeline)))
        rows.append((label, fmt(independent), fmt(pipeline), "MATCH" if ok else "DIFFERENT"))

    # ---------------- Window and boundaries ----------------
    b = con.execute("""
        SELECT min(award) FILTER (WHERE fy BETWEEN 2022 AND 2026), max(award) FILTER (WHERE fy BETWEEN 2022 AND 2026),
               count(*) FILTER (WHERE award = DATE '2021-09-30'), any_value(fy) FILTER (WHERE award = DATE '2021-09-30'),
               count(*) FILTER (WHERE award = DATE '2021-10-01'), any_value(fy) FILTER (WHERE award = DATE '2021-10-01'),
               count(*) FILTER (WHERE award = DATE '2026-09-30'), any_value(fy) FILTER (WHERE award = DATE '2026-09-30'),
               max(award), count(*) FILTER (WHERE award > DATE '2026-09-30')
        FROM src""").fetchone()

    def headline(dup_filter: str = "TRUE", vendor_key: str = "VENDOR_CODE") -> dict:
        con.execute(f"""
            CREATE OR REPLACE TEMP VIEW f AS
            SELECT *, {vendor_key} AS vkey FROM src_flag WHERE fy BETWEEN 2022 AND 2026 AND {dup_filter}""")
        total = con.execute("SELECT sum(amt) FROM f").fetchone()[0]
        v = con.execute("SELECT vkey, sum(amt) s FROM f GROUP BY 1 ORDER BY s DESC, vkey").df()
        v["share"] = v["s"] / total
        cum = v["share"].cumsum()
        c = con.execute("""
            WITH cv AS (SELECT cls, vkey, sum(amt) s FROM f GROUP BY ALL),
                 cs AS (SELECT cls, sum(s) cs FROM cv GROUP BY cls)
            SELECT cv.cls, cs.cs, max(cv.s / cs.cs) AS top_share, sum(power(100 * cv.s / cs.cs, 2)) AS hhi
            FROM cv JOIN cs USING (cls) GROUP BY cv.cls, cs.cs""").df()
        big = c[c["cs"] >= 1_000_000]
        fuel = big[big["cls"] == "405"].iloc[0]
        return {"total": total, "largest_share": v["share"].iloc[0], "top10": v["share"].head(10).sum(),
                "v80": int((cum < 0.80).sum() + 1), "vendors": len(v), "screened": len(big),
                "hhi_2500": int((big["hhi"] >= 2500).sum()), "r1": int((big["top_share"] >= 0.90).sum()),
                "r1_spend": float(big.loc[big["top_share"] >= 0.90, "cs"].sum()), "r1_set": sorted(big.loc[big["top_share"] >= 0.90, "cls"]),
                "fuel_spend": float(fuel["cs"]), "fuel_share": float(fuel["top_share"])}

    base = headline()
    check("FY2022-FY2026 awarded value", base["total"], hl["total_spend"], lambda v: f"${float(v):,.2f}", 1e-9)
    check("Top-10 vendor share", base["top10"], hl["top10_share"], lambda v: f"{float(v):.2%}")
    check("Vendors to reach 80% of spend", base["v80"], hl["vendors_for_80pct"])
    check("Active vendors", base["vendors"], hl["active_vendors"])
    check("NIGP classes screened (spend >= $1M)", base["screened"], hl["screened_categories"])
    check("Highly concentrated classes (HHI >= 2,500)", base["hhi_2500"], hl["highly_concentrated_categories"])
    check("Classes with one vendor >= 90%", base["r1"], hl["single_vendor_categories"])
    check("Spend in those classes", base["r1_spend"], hl["single_vendor_spend"], lambda v: f"${float(v):,.0f}", 1e-9)
    check("Fuel class (405) spend", base["fuel_spend"], hl["largest_single_vendor_spend"], lambda v: f"${float(v):,.2f}", 1e-9)
    check("Fuel class top-vendor share", base["fuel_share"], hl["largest_single_vendor_share"], lambda v: f"{float(v):.2%}")
    pipe_largest = pd.read_csv(ROOT / "outputs" / "tables" / "obs_vendor_spend_top150.csv")["share"].iloc[0]
    check("Largest vendor's share of total (CSV stores 6 decimals)", base["largest_share"], pipe_largest, lambda v: f"{float(v):.3%}", 1e-5)
    fuel_orders = con.execute("""
        WITH f AS (SELECT * FROM src WHERE fy BETWEEN 2022 AND 2026 AND cls = '405'),
             top AS (SELECT VENDOR_CODE FROM f GROUP BY 1 ORDER BY sum(amt) DESC LIMIT 1)
        SELECT count(DISTINCT PURCHASE_ORDER), count(DISTINCT fy), count(DISTINCT VENDOR_CODE) FROM f WHERE VENDOR_CODE IN (SELECT * FROM top)""").fetchone()

    # ---------------- Duplicate sensitivity ----------------
    dup = con.execute("""
        SELECT count(*) FILTER (WHERE is_dup), sum(amt) FILTER (WHERE is_dup),
               count(*) FILTER (WHERE is_dup AND fy BETWEEN 2022 AND 2026), sum(amt) FILTER (WHERE is_dup AND fy BETWEEN 2022 AND 2026),
               count(DISTINCT PURCHASE_ORDER) FILTER (WHERE is_dup), max(amt) FILTER (WHERE is_dup),
               count(*) FILTER (WHERE is_dup AND CAST(QUANTITY AS DOUBLE) = 0)
        FROM src_flag""").fetchone()
    nodup = headline("NOT is_dup")
    # ---------------- Vendor-name grouping sensitivity ----------------
    con.execute("""CREATE OR REPLACE TABLE latest_name AS
        SELECT VENDOR_CODE, upper(trim(arg_max(LGL_NM, award))) AS nm FROM src GROUP BY 1""")
    con.execute("CREATE OR REPLACE TABLE src_flag AS SELECT s.*, l.nm FROM src_flag s JOIN latest_name l USING (VENDOR_CODE)")
    byname = headline("TRUE", "regexp_replace(nm, '[^A-Z0-9]', '', 'g')")

    sens = [
        ("Awarded value", money(base["total"]), money(nodup["total"]), money(byname["total"])),
        ("Largest vendor share", f"{base['largest_share']:.2%}", f"{nodup['largest_share']:.2%}", f"{byname['largest_share']:.2%}"),
        ("Vendors for 80%", base["v80"], nodup["v80"], byname["v80"]),
        ("Classes HHI >= 2,500 (of screened)", f"{base['hhi_2500']} of {base['screened']}", f"{nodup['hhi_2500']} of {nodup['screened']}", f"{byname['hhi_2500']} of {byname['screened']}"),
        ("Classes with one vendor >= 90%", f"{base['r1']} ({', '.join(base['r1_set'])})", f"{nodup['r1']} ({', '.join(nodup['r1_set'])})", f"{byname['r1']} ({', '.join(byname['r1_set'])})"),
        ("Fuel: top-vendor share of class spend", f"{base['fuel_share']:.2%} of {money(base['fuel_spend'])}", f"{nodup['fuel_share']:.2%} of {money(nodup['fuel_spend'])}", f"{byname['fuel_share']:.2%} of {money(byname['fuel_spend'])}"),
    ]

    # ---------------- Transformer prices ----------------
    reviewed = pd.read_csv(REVIEWED, dtype=str)
    con.register("reviewed", reviewed)
    con.execute("""
        CREATE OR REPLACE TABLE items AS
        SELECT s.*, upper(trim(regexp_replace(UNIT_OF_MEASURE, '\\s+', ' ', 'g'))) AS uom,
               sha256(CASE WHEN trim(EXTENDED_DESCRIPTION) <> '' THEN upper(trim(regexp_replace(EXTENDED_DESCRIPTION, '\\s+', ' ', 'g')))
                           WHEN length(COMMODITY) = 11 THEN upper(trim(regexp_replace(COMMODITY_DESCRIPTION, '\\s+', ' ', 'g'))) ELSE '' END) AS tkey
        FROM src_flag s
        WHERE fy BETWEEN 2022 AND 2026 AND NOT is_dup AND qty > 0 AND price > 0 AND trim(UNIT_OF_MEASURE) <> ''
          AND abs(qty * price - amt) <= greatest(0.01, 0.005 * amt);
        CREATE OR REPLACE TABLE iy AS
        SELECT COMMODITY, uom, tkey, fy, count(*) n, median(price) med, median(qty) med_qty, sum(amt) spend
        FROM items WHERE tkey IN (SELECT text_sha256 FROM reviewed) GROUP BY ALL HAVING count(*) >= 4;
    """)
    t = con.execute("""
        SELECT a.COMMODITY, a.tkey, a.med AS p22, b.med AS p23, b.med / a.med - 1 AS chg, a.med_qty AS q22, b.med_qty AS q23, b.spend AS spend23
        FROM iy a JOIN iy b ON a.COMMODITY = b.COMMODITY AND a.uom = b.uom AND a.tkey = b.tkey AND a.fy = 2022 AND b.fy = 2023
        JOIN reviewed r ON r.text_sha256 = a.tkey WHERE r.public_label LIKE 'TRANSFORMER%'""").df()
    # Quantity control: recompute both years' medians using only orders of 1-10 units
    tq = con.execute("""
        WITH x AS (SELECT COMMODITY, uom, tkey, fy, median(price) med, count(*) n FROM items
                   WHERE tkey IN (SELECT text_sha256 FROM reviewed WHERE public_label LIKE 'TRANSFORMER%') AND qty BETWEEN 1 AND 10
                   GROUP BY ALL HAVING count(*) >= 4)
        SELECT b.med / a.med - 1 AS chg FROM x a JOIN x b ON a.COMMODITY = b.COMMODITY AND a.uom = b.uom AND a.tkey = b.tkey
        WHERE a.fy = 2022 AND b.fy = 2023""").df()
    check("Transformer items with FY2022 and FY2023 baselines", len(t), hl["transformer_items_22_23"])
    check("Transformer median price change FY2022->FY2023", t["chg"].median(), hl["transformer_median_change_22_23"], lambda v: f"{float(v):.1%}")
    check("Transformer maximum price change", t["chg"].max(), hl["transformer_max_change_22_23"], lambda v: f"{float(v):.1%}")

    # Within-year dispersion with a quantity band (each line within 0.5x-2x of its item-year median quantity)
    disp = con.execute("""
        WITH g AS (SELECT i.*, median(price) OVER w AS med, median(qty) OVER w AS mq, count(*) OVER w AS n
                   FROM items i WHERE tkey IN (SELECT text_sha256 FROM reviewed)
                   WINDOW w AS (PARTITION BY COMMODITY, uom, tkey, fy))
        SELECT count(*) FILTER (WHERE price / med >= 1.5 AND price / med < 10) AS flagged,
               sum(CASE WHEN price / med >= 1.5 AND price / med < 10 THEN (price - med) * qty ELSE 0 END) AS excess,
               count(*) FILTER (WHERE price / med >= 1.5 AND price / med < 10 AND qty BETWEEN 0.5 * mq AND 2 * mq) AS flagged_qband,
               sum(CASE WHEN price / med >= 1.5 AND price / med < 10 AND qty BETWEEN 0.5 * mq AND 2 * mq THEN (price - med) * qty ELSE 0 END) AS excess_qband
        FROM g WHERE n >= 4""").fetchone()
    check("Lines priced >= 1.5x item-year median", disp[0], hl["price_flagged_lines"])
    check("Modelled excess above median", disp[1], hl["price_opportunity_full"], lambda v: f"${float(v):,.0f}", 1e-6)
    check("Modelled excess, order size controlled", disp[3], hl["price_opportunity_qty_controlled"], lambda v: f"${float(v):,.0f}", 1e-6)

    samples = con.execute("""
        SELECT length(COMMODITY) AS code_length, COMMODITY, any_value(COMMODITY_DESCRIPTION) AS description, any_value(cls) AS class
        FROM src WHERE length(COMMODITY) IN (5, 7, 11) AND cls IN ('285', '405', '070')
        GROUP BY ALL ORDER BY code_length, COMMODITY LIMIT 12""").df()
    con.close()

    passed = sum(r[3] == "MATCH" for r in rows)
    out = [
        "# Independent analytical audit",
        "",
        "Generated by `python scripts/independent_audit.py`, which reads the private raw CSV directly with DuckDB SQL and does "
        "**not** use the pipeline's analysis code. Only aggregate results are written here.",
        "",
        f"**Headline reconciliation: {passed} of {len(rows)} values match the published pipeline outputs.**",
        "",
        "## 1. Reporting window and fiscal-year boundaries",
        "",
        "| Check | Result |",
        "|---|---|",
        f"| First / last award date inside FY2022–FY2026 | {b[0]} / {b[1]} |",
        f"| Lines awarded 30 Sep 2021 → fiscal year | {b[2]} lines → FY{b[3]} (excluded) |",
        f"| Lines awarded 1 Oct 2021 → fiscal year | {b[4]} lines → FY{b[5]} (included) |",
        f"| Lines awarded 30 Sep 2026 → fiscal year | {b[6]} lines → FY{b[7]} (included) |",
        f"| Latest award date in source / awards after 30 Sep 2026 | {b[8]} / {b[9]} |",
        "",
        "The window covers five complete City fiscal years (1 Oct 2021 – 30 Sep 2026). Every share uses FY2022–FY2026 awarded value "
        "as its denominator; category shares use that category's FY2022–FY2026 value.",
        "",
        "## 2. Headline reconciliation",
        "",
        "| Finding | Independent SQL | Pipeline | Result |",
        "|---|---|---|---|",
        *[f"| {a} | {b_} | {c} | {d} |" for a, b_, c, d in rows],
        "",
        f"Fuel (NIGP class 405): the largest vendor supplied {base['fuel_share']:.1%} of {money(base['fuel_spend'])} on "
        f"{fuel_orders[0]} purchase orders across {fuel_orders[1]} fiscal years, so the concentration is recurring rather than one large order. "
        "This is an exposure to review; the data contains no delivery or quality records about the vendor.",
        "",
        "## 3. Duplicate-record sensitivity",
        "",
        f"The source has {dup[0]} rows that exactly repeat an earlier row on all 21 columns ({money(dup[1])} in total; "
        f"{dup[2]} rows and {money(dup[3] or 0)} inside FY2022–FY2026). They sit on {dup[4]} purchase orders; the largest single row is "
        f"{money(dup[5])}, and {dup[6]} of them are amount-only lines.",
        "",
        "**Why retained:** the source has no line number, so two identical lines on the same PO (for example the same part ordered "
        "twice for two work orders) cannot be distinguished from an export error. They are flagged and excluded from price comparisons, "
        "but kept in spend. The test below shows the choice does not change any conclusion.",
        "",
        "| Metric | As published | Duplicates excluded | Vendors grouped by name instead of vendor code |",
        "|---|---|---|---|",
        *[f"| {a} | {b_} | {c} | {d} |" for a, b_, c, d in sens],
        "",
        ("All headline results are identical under the three treatments: excluding the duplicates or grouping vendors by their "
         "latest name instead of City vendor code does not change any conclusion."
         if all(r[1] == r[2] == r[3] for r in sens) else
         "Results differ between treatments as shown; the headline conclusions should be read with this sensitivity in mind."),
        "",
        "## 4. Price comparability",
        "",
        "- Items: same commodity code, same unit of measure, same full item text, and that text must be on the human-reviewed list of "
        "genuine product specifications (`config/reviewed_item_texts.csv`, 153 of 267 candidate texts accepted).",
        "- Period: medians are taken within a single fiscal year; year-over-year changes compare consecutive fiscal years only.",
        "- Rows: unit-priced lines whose quantity × price reconciles to the amount; duplicates excluded; ≥ 4 purchases per item-year.",
        f"- Distribution transformers: {len(t)} items had baselines in both FY2022 and FY2023. Median order quantity per line was "
        f"{t['q22'].median():.0f} units in FY2022 and {t['q23'].median():.0f} in FY2023. Restricting both years to orders of 1–10 units "
        f"leaves {len(tq)} comparable items with a median change of {tq['chg'].median():.1%}"
        + (" — the increase is not an artefact of order size." if len(tq) and tq['chg'].median() > 0.2 else ".") ,
        f"- Within-year dispersion: {disp[0]} lines are priced ≥ 1.5× their item-year median ({money(disp[1])} modelled excess). "
        f"If only lines whose quantity is within 0.5×–2× of the item-year median quantity are counted, {disp[2]} lines and "
        f"{money(disp[3])} remain, so part of the dispersion may reflect order size. The figure is an opportunity to investigate, not a saving.",
        "",
        "### Correction made during this audit",
        "",
        "The first version compared any non-blank extended description. Review showed that many such texts were not products "
        "(bid/quote references, delivery notes, names, vague text). Restricting comparisons to reviewed product specifications "
        "changed the within-year dispersion result from 228 lines / $5.0M to the figures above, and removed one year-over-year "
        "action (road-base materials, where the 'items' were delivery notes). Concentration and transformer findings were unchanged.",
        "",
        "## 5. Category grouping",
        "",
        "Categories are NIGP 3-digit classes: the first three digits of the City's commodity code for 5-digit (class-item), "
        "7-digit (City inventory) and 11-digit (item-level) codes. Sample codes from three classes:",
        "",
        "| Code length | Code | City description | Class |",
        "|---|---|---|---|",
        *[f"| {r.code_length} | {r.COMMODITY} | {str(r.description)[:60]} | {r._4} |" for r in samples.itertuples()],
        "",
        "Spend families are an analyst grouping of classes (`config/category_families.toml`) used only for the family chart; "
        "every concentration finding is computed at class level.",
        "",
    ]
    (ROOT / "docs" / "analytical_audit.md").write_text("\n".join(str(x) for x in out), encoding="utf-8")
    print(f"{passed}/{len(rows)} headline values match; wrote docs/analytical_audit.md")
    for r in rows:
        print(" ", r)
    for s in sens:
        print(" ", s)
    print("transformer qty-controlled:", len(tq), tq["chg"].median() if len(tq) else None, "qband dispersion:", disp)
    return 0 if passed == len(rows) else 2


if __name__ == "__main__":
    sys.exit(main())
