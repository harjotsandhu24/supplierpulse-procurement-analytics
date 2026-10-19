-- Q02  How concentrated is total purchasing spend across vendors?
-- Data: City of Austin (observed), focus window.
-- HHI = sum of squared percentage shares (0-10,000). Vendors-for-80% counts vendors (largest first)
-- needed to reach 80% of spend.
WITH v AS (
    SELECT vendor_code, SUM(line_amount) AS spend FROM v_obs_focus_line GROUP BY vendor_code
),
s AS (
    SELECT vendor_code, spend,
           spend / SUM(spend) OVER () AS share,
           SUM(spend) OVER (ORDER BY spend DESC, vendor_code ROWS UNBOUNDED PRECEDING) / SUM(spend) OVER () AS cum_share,
           ROW_NUMBER() OVER (ORDER BY spend DESC, vendor_code) AS rn
    FROM v
)
SELECT
    ROUND(SUM(spend), 2)                             AS total_spend,
    COUNT(*)                                         AS active_vendors,
    SUM(POWER(share * 100, 2))                       AS vendor_hhi,
    SUM(share) FILTER (WHERE rn <= 10)               AS top10_share,
    SUM(share) FILTER (WHERE rn <= 20)               AS top20_share,
    COUNT(*) FILTER (WHERE cum_share - share < 0.80) AS vendors_for_80pct
FROM s;
