-- View: one row per SYNTHETIC purchase-order line with its delivery outcome at the as-of date.
-- Definitions match src/supplierpulse/delivery.py:
--   due      = not cancelled and promised_date <= as_of_date
--   on_time  = due and first receipt on/before promised_date + grace
--   in_full  = due and total received >= ordered x (1 - tolerance)
--   otif     = due and quantity received by promised_date + grace >= ordered x (1 - tolerance)
--   A due line with no receipts is never on time, in full or OTIF.
CREATE OR REPLACE VIEW v_syn_line_delivery AS
WITH p AS (SELECT * FROM params),
line AS (
    SELECT l.*, po.supplier_id, po.category_id, po.order_date
    FROM syn_po_line AS l
    JOIN syn_purchase_order AS po USING (po_id)
),
rcpt AS (
    SELECT
        r.*,
        SUM(r.received_qty) OVER (PARTITION BY r.po_line_id ORDER BY r.receipt_date, r.receipt_id) AS cum_qty
    FROM syn_goods_receipt AS r
),
agg AS (
    SELECT
        r.po_line_id,
        COUNT(*)                         AS receipts,
        SUM(r.received_qty)              AS received_qty,
        SUM(r.rejected_qty)              AS rejected_qty,
        SUM(CASE WHEN r.receipt_date <= l.promised_date + to_days(CAST(p.on_time_grace_days AS INTEGER))
                 THEN r.received_qty ELSE 0 END) AS qty_by_promise,
        MIN(r.receipt_date)              AS first_receipt_date,
        MAX(r.receipt_date)              AS last_receipt_date,
        MIN(CASE WHEN r.cum_qty >= l.ordered_qty * (1 - p.in_full_tolerance) THEN r.receipt_date END) AS completion_date
    FROM rcpt AS r
    JOIN line AS l USING (po_line_id)
    CROSS JOIN p
    GROUP BY r.po_line_id
),
base AS (
    SELECT
        l.*,
        COALESCE(a.receipts, 0)       AS receipts,
        COALESCE(a.received_qty, 0)   AS received_qty,
        COALESCE(a.rejected_qty, 0)   AS rejected_qty,
        COALESCE(a.qty_by_promise, 0) AS qty_by_promise,
        a.first_receipt_date,
        a.last_receipt_date,
        a.completion_date,
        p.as_of_date,
        p.on_time_grace_days,
        p.in_full_tolerance,
        NOT l.cancelled AND l.promised_date <= p.as_of_date AS due
    FROM line AS l
    LEFT JOIN agg AS a USING (po_line_id)
    CROSS JOIN p
)
SELECT
    *,
    ordered_qty * unit_price AS line_value,
    due AND first_receipt_date IS NOT NULL
        AND first_receipt_date <= promised_date + to_days(CAST(on_time_grace_days AS INTEGER)) AS on_time,
    due AND received_qty   >= ordered_qty * (1 - in_full_tolerance) AS in_full,
    due AND qty_by_promise >= ordered_qty * (1 - in_full_tolerance) AS otif,
    completion_date IS NOT NULL AS complete,
    NOT cancelled AND NOT short_closed AND completion_date IS NULL AS is_open,
    NOT cancelled AND NOT short_closed AND completion_date IS NULL AND promised_date < as_of_date AS overdue,
    CASE WHEN NOT due THEN NULL
         WHEN completion_date IS NOT NULL THEN GREATEST(0, date_diff('day', promised_date, completion_date))
         WHEN short_closed THEN GREATEST(0, date_diff('day', promised_date, COALESCE(last_receipt_date, short_close_date)))
         ELSE GREATEST(0, date_diff('day', promised_date, as_of_date)) END AS days_late,
    date_diff('day', order_date, completion_date) AS lead_time_days,
    CASE WHEN promised_date < as_of_date - INTERVAL 1 YEAR + INTERVAL 1 DAY THEN 'prior_12m' ELSE 'last_12m' END AS due_period
FROM base;
