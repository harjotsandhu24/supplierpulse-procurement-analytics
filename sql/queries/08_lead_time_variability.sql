-- Q08  Whose lead times are unpredictable?
-- Data: SYNTHETIC demonstration. Lead time = order date to the receipt that completed the line,
-- completed lines only. Variability is the sample standard deviation in days.
SELECT
    supplier_id,
    COUNT(*)                                          AS completed_lines,
    AVG(lead_time_days)                               AS avg_lead_time,
    STDDEV_SAMP(lead_time_days)                       AS lead_time_sd,
    STDDEV_SAMP(lead_time_days) / AVG(lead_time_days) AS lead_time_cv,
    QUANTILE_CONT(lead_time_days, 0.9)                AS lead_time_p90,
    MAX(lead_time_days)                               AS max_lead_time
FROM v_syn_line_delivery
WHERE complete
GROUP BY supplier_id
ORDER BY lead_time_sd DESC, supplier_id;
