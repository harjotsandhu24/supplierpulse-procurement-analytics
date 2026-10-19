-- Q11  Whose delivery performance is deteriorating?
-- Data: SYNTHETIC demonstration. Compares OTIF on lines due in the prior 12 months with lines
-- due in the last 12 months before the as-of date.
WITH t AS (
    SELECT supplier_id, due_period,
           COUNT(*)                                  AS due_lines,
           AVG(CASE WHEN otif THEN 1.0 ELSE 0.0 END) AS otif_rate
    FROM v_syn_line_delivery
    WHERE due
    GROUP BY ALL
)
SELECT
    supplier_id,
    MAX(CASE WHEN due_period = 'prior_12m' THEN due_lines END) AS due_lines_prior_12m,
    MAX(CASE WHEN due_period = 'prior_12m' THEN otif_rate END) AS otif_prior_12m,
    MAX(CASE WHEN due_period = 'last_12m'  THEN due_lines END) AS due_lines_last_12m,
    MAX(CASE WHEN due_period = 'last_12m'  THEN otif_rate END) AS otif_last_12m,
    MAX(CASE WHEN due_period = 'last_12m'  THEN otif_rate END)
      - MAX(CASE WHEN due_period = 'prior_12m' THEN otif_rate END) AS otif_change
FROM t
GROUP BY supplier_id
ORDER BY otif_change NULLS LAST, supplier_id;
