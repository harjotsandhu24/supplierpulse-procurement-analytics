-- Q05  How much spend flows through master agreements, and where is standalone buying recurring?
-- Data: City of Austin (observed), focus window. In this source every delivery order (DO) references
-- a master agreement; contract-type (CT) and purchase-order-type (PO) orders do not.
-- Part 1: coverage by order type. Part 2: classes with >= 10 standalone orders and >= $250k (rule R4).
WITH t AS (
    SELECT po_type, has_master_agreement,
           COUNT(DISTINCT purchase_order) AS orders,
           SUM(line_amount)               AS spend
    FROM v_obs_focus_line
    GROUP BY ALL
),
coverage AS (
    SELECT 1 AS part, 'Coverage by order type' AS section, po_type AS item, has_master_agreement,
           orders, ROUND(spend, 2) AS spend, spend / SUM(spend) OVER () AS share_of_spend
    FROM t
),
standalone AS (
    SELECT 2 AS part, 'Recurring standalone classes' AS section, class_label AS item, FALSE AS has_master_agreement,
           COUNT(DISTINCT purchase_order) AS orders, ROUND(SUM(line_amount), 2) AS spend, NULL::DOUBLE AS share_of_spend
    FROM v_obs_focus_line
    WHERE NOT has_master_agreement
    GROUP BY class_label
    HAVING COUNT(DISTINCT purchase_order) >= 10 AND SUM(line_amount) >= 250000
)
SELECT section, item, has_master_agreement, orders, spend, share_of_spend
FROM (SELECT * FROM coverage UNION ALL SELECT * FROM standalone)
ORDER BY part, spend DESC, item;
