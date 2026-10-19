-- Q03  How has spend in each spend family changed across fiscal years?
-- Data: City of Austin (observed), focus window. Families are an analyst grouping of NIGP classes
-- (config/category_families.toml). YoY change is NULL in the first year.
WITH f AS (
    SELECT spend_family, fiscal_year, SUM(line_amount) AS spend
    FROM v_obs_focus_line
    GROUP BY spend_family, fiscal_year
)
SELECT
    spend_family,
    fiscal_year,
    ROUND(spend, 2) AS spend,
    spend / LAG(spend) OVER (PARTITION BY spend_family ORDER BY fiscal_year) - 1 AS yoy_change,
    spend / SUM(spend) OVER (PARTITION BY fiscal_year)                           AS share_of_year
FROM f
ORDER BY spend_family, fiscal_year;
