-- Q06  Where do we pay materially different prices for the same item in the same year?
-- Data: City of Austin (observed), focus window. Like-for-like rules (same as price.py):
--   unit-priced, item-specific, non-duplicate lines; same commodity code + unit of measure +
--   normalised description + fiscal year; >= min_lines_per_item_year lines per item-year.
--   Baseline = item-year median. Lines >= above_baseline_ratio x median are flagged; ratios
--   <= 0.25 or >= 10 are treated as unit/entry inconsistencies and excluded from the excess.
WITH c AS (
    SELECT *, commodity_code || ' | ' || uom || ' | ' || item_description AS item_key
    FROM v_obs_focus_line
    WHERE line_type = 'unit_priced' AND item_specific AND NOT possible_duplicate
),
g AS (
    SELECT c.*,
           COUNT(*)           OVER (PARTITION BY item_key, fiscal_year) AS item_year_lines,
           MEDIAN(unit_price) OVER (PARTITION BY item_key, fiscal_year) AS baseline_price
    FROM c
),
x AS (
    SELECT g.*,
           unit_price / baseline_price AS ratio,
           CASE WHEN unit_price / baseline_price <= 0.25 OR unit_price / baseline_price >= 10 THEN 'probable_unit_or_entry_issue'
                WHEN unit_price / baseline_price >= p.above_baseline_ratio THEN 'above_baseline'
                ELSE 'within_range' END AS price_flag
    FROM g CROSS JOIN params AS p
    WHERE g.item_year_lines >= p.min_lines_per_item_year
)
SELECT
    item_key,
    fiscal_year,
    ANY_VALUE(uom)                                        AS uom,
    COUNT(*)                                              AS lines,
    COUNT(DISTINCT vendor_code)                           AS vendors,
    ANY_VALUE(baseline_price)                             AS baseline_price,
    MAX(unit_price)                                       AS max_price,
    COUNT(*) FILTER (WHERE price_flag = 'above_baseline') AS flagged_lines,
    ROUND(SUM(CASE WHEN price_flag = 'above_baseline'
                   THEN (unit_price - baseline_price) * quantity ELSE 0 END), 2) AS excess_vs_baseline
FROM x
GROUP BY item_key, fiscal_year
HAVING COUNT(*) FILTER (WHERE price_flag = 'above_baseline') > 0
ORDER BY excess_vs_baseline DESC, item_key, fiscal_year;
