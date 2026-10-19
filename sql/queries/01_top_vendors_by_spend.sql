-- Q01  Which vendors receive the most purchasing spend?
-- Data: City of Austin (observed), focus-window fiscal years. Spend = awarded PO line value (USD).
-- Ties on spend are broken by vendor code so the ranking is deterministic.
WITH v AS (
    SELECT vendor_code, vendor_name,
           SUM(line_amount)               AS spend,
           COUNT(DISTINCT purchase_order) AS po_count,
           COUNT(*)                       AS line_count,
           COUNT(DISTINCT nigp_class)     AS categories
    FROM v_obs_focus_line
    GROUP BY vendor_code, vendor_name
)
SELECT
    ROW_NUMBER() OVER (ORDER BY spend DESC, vendor_code)                          AS spend_rank,
    vendor_code,
    vendor_name,
    ROUND(spend, 2)                                                               AS spend,
    spend / SUM(spend) OVER ()                                                    AS share_of_total,
    SUM(spend) OVER (ORDER BY spend DESC, vendor_code ROWS UNBOUNDED PRECEDING)
        / SUM(spend) OVER ()                                                      AS cumulative_share,
    po_count,
    ROUND(spend / po_count, 2)                                                    AS avg_po_value,
    categories
FROM v
ORDER BY spend_rank
LIMIT 15;
