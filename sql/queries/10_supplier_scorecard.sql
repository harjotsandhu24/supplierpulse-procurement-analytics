-- Q10  How do suppliers rank on a transparent, weighted performance score?
-- Data: SYNTHETIC demonstration. See sql/views/03_v_syn_supplier_scorecard.sql for the formulas.
-- Suppliers with fewer than min_lines_ranked due lines are not ranked; under min_lines_provisional
-- they are not scored at all. Ties share a rank.
SELECT
    supplier_id,
    evidence_status,
    due_lines,
    otif_rate,
    reject_rate,
    lead_time_sd,
    avg_days_late_all_due,
    ROUND(score_otif, 1)                 AS score_otif,
    ROUND(score_quality, 1)              AS score_quality,
    ROUND(score_leadtime_consistency, 1) AS score_leadtime_consistency,
    ROUND(score_lateness, 1)             AS score_lateness,
    weight_used,
    performance_score,
    score_rank
FROM v_syn_supplier_scorecard
ORDER BY score_rank NULLS LAST, performance_score DESC NULLS LAST, supplier_id;
