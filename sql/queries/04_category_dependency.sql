-- Q04  In which categories does one vendor dominate spend (single-source dependency)?
-- Data: City of Austin (observed), focus window. Screens NIGP classes with spend >= min_category_spend.
-- R1 = top vendor share >= single_vendor_share; R2 = HHI >= hhi_highly_concentrated (and not R1).
WITH cv AS (
    SELECT nigp_class, class_label, vendor_code, vendor_name, SUM(line_amount) AS spend
    FROM v_obs_focus_line
    GROUP BY ALL
),
s AS (
    SELECT cv.*,
           spend / SUM(spend) OVER (PARTITION BY nigp_class) AS share,
           ROW_NUMBER() OVER (PARTITION BY nigp_class ORDER BY spend DESC, vendor_code) AS rn
    FROM cv
),
c AS (
    SELECT nigp_class,
           ANY_VALUE(class_label)                     AS class_label,
           SUM(spend)                                 AS category_spend,
           COUNT(*)                                   AS vendor_count,
           MAX(CASE WHEN rn = 1 THEN vendor_name END) AS top_vendor,
           MAX(CASE WHEN rn = 1 THEN share END)       AS top_vendor_share,
           SUM(POWER(share * 100, 2))                 AS hhi
    FROM s
    GROUP BY nigp_class
)
SELECT
    c.nigp_class, c.class_label, ROUND(c.category_spend, 2) AS category_spend, c.vendor_count,
    c.top_vendor, c.top_vendor_share, c.hhi,
    CASE WHEN c.top_vendor_share >= p.single_vendor_share THEN 'R1 single-vendor dependency'
         WHEN c.hhi >= p.hhi_highly_concentrated THEN 'R2 highly concentrated'
         ELSE 'Not flagged' END AS dependency_flag
FROM c CROSS JOIN params AS p
WHERE c.category_spend >= p.min_category_spend
ORDER BY (c.top_vendor_share >= p.single_vendor_share) DESC, c.category_spend DESC;
