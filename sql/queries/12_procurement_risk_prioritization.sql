-- Q12  Which suppliers combine weak performance with high dependency (act first)?
-- Data: SYNTHETIC demonstration. Performance comes from the scorecard; dependency from the
-- supplier's largest category share, the number of suppliers in that category and its share of
-- total spend. The two are kept separate and only combined into an action quadrant.
WITH cat AS (
    SELECT category_id, supplier_id, SUM(line_value) AS spend
    FROM v_syn_line_delivery
    WHERE NOT cancelled
    GROUP BY ALL
),
cs AS (
    SELECT cat.*,
           spend / SUM(spend) OVER (PARTITION BY category_id) AS category_share,
           COUNT(*)           OVER (PARTITION BY category_id) AS suppliers_in_category
    FROM cat
),
ranked AS (
    SELECT cs.*, ROW_NUMBER() OVER (PARTITION BY supplier_id ORDER BY category_share DESC, category_id) AS rn
    FROM cs
),
tot AS (
    SELECT supplier_id, SUM(spend) / SUM(SUM(spend)) OVER () AS share_of_total_spend
    FROM cat
    GROUP BY supplier_id
),
dep AS (
    SELECT r.supplier_id, r.category_id AS main_category_id, r.category_share AS max_category_share,
           r.suppliers_in_category, tot.share_of_total_spend,
           CASE WHEN r.suppliers_in_category = 1
                  OR r.category_share >= p.high_dependency_category_share
                  OR tot.share_of_total_spend >= p.high_dependency_total_share THEN 'High'
                WHEN r.category_share >= p.medium_dependency_category_share
                  OR tot.share_of_total_spend >= p.medium_dependency_total_share THEN 'Medium'
                ELSE 'Low' END AS dependency_risk
    FROM ranked AS r
    JOIN tot USING (supplier_id)
    CROSS JOIN params AS p
    WHERE r.rn = 1
),
q AS (
    SELECT
        sc.supplier_id,
        sc.evidence_status,
        sc.performance_score,
        dep.main_category_id,
        dep.max_category_share,
        dep.share_of_total_spend,
        dep.dependency_risk,
        CASE WHEN sc.evidence_status = 'Insufficient evidence' THEN 'Insufficient evidence'
             WHEN dep.dependency_risk = 'High' AND sc.performance_score < p.tier_acceptable THEN 'Critical - act now'
             WHEN dep.dependency_risk = 'High' THEN 'Strategic - protect and monitor'
             WHEN sc.performance_score < p.tier_acceptable THEN 'Develop or replace'
             ELSE 'Maintain' END AS action_quadrant
    FROM v_syn_supplier_scorecard AS sc
    JOIN dep USING (supplier_id)
    CROSS JOIN params AS p
)
SELECT *
FROM q
ORDER BY CASE action_quadrant WHEN 'Critical - act now' THEN 1 WHEN 'Develop or replace' THEN 2
                              WHEN 'Strategic - protect and monitor' THEN 3 WHEN 'Maintain' THEN 4 ELSE 5 END,
         performance_score, supplier_id;
