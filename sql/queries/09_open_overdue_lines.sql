-- Q09  Which open purchase-order lines are past their promised date?
-- Data: SYNTHETIC demonstration. Open = not cancelled, not short-closed, not fully received.
SELECT
    d.po_line_id,
    d.supplier_id,
    s.supplier_name,
    d.item_id,
    d.order_date::DATE                                        AS order_date,
    d.promised_date::DATE                                     AS promised_date,
    d.ordered_qty,
    d.received_qty,
    d.ordered_qty - d.received_qty                            AS open_qty,
    ROUND((d.ordered_qty - d.received_qty) * d.unit_price, 2) AS open_value,
    d.days_late                                               AS days_past_promise
FROM v_syn_line_delivery AS d
JOIN syn_supplier AS s USING (supplier_id)
WHERE d.overdue
ORDER BY days_past_promise DESC, d.po_line_id;
