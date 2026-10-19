-- Q07  Which suppliers deliver on time and in full?
-- Data: SYNTHETIC demonstration. Measured per PO line; only due lines (not cancelled, promised
-- date on/before the as-of date) are in the denominators. Unreceived due lines count as failures.
SELECT
    d.supplier_id,
    s.supplier_name,
    COUNT(*) FILTER (WHERE due)                                     AS due_lines,
    COUNT(*) FILTER (WHERE cancelled)                               AS cancelled_lines,
    AVG(CASE WHEN on_time THEN 1.0 ELSE 0.0 END) FILTER (WHERE due) AS on_time_rate,
    AVG(CASE WHEN in_full THEN 1.0 ELSE 0.0 END) FILTER (WHERE due) AS in_full_rate,
    AVG(CASE WHEN otif    THEN 1.0 ELSE 0.0 END) FILTER (WHERE due) AS otif_rate,
    COUNT(*) FILTER (WHERE due AND days_late > 0)                   AS late_lines,
    AVG(days_late) FILTER (WHERE due AND days_late > 0)             AS avg_days_late_when_late,
    COUNT(*) FILTER (WHERE short_closed)                            AS short_closed_lines
FROM v_syn_line_delivery AS d
JOIN syn_supplier AS s USING (supplier_id)
GROUP BY d.supplier_id, s.supplier_name
ORDER BY otif_rate DESC, d.supplier_id;
