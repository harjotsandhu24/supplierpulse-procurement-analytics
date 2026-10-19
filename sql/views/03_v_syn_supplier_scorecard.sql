-- View: SYNTHETIC supplier scorecard computed entirely in SQL from v_syn_line_delivery.
-- Component scaling, weights, evidence thresholds and ranking match src/supplierpulse/scoring.py.
CREATE OR REPLACE VIEW v_syn_supplier_scorecard AS
WITH p AS (SELECT * FROM params),
m AS (
    SELECT
        supplier_id,
        COUNT(*) FILTER (WHERE due)                                   AS due_lines,
        AVG(CASE WHEN otif THEN 1.0 ELSE 0.0 END) FILTER (WHERE due)  AS otif_rate,
        AVG(days_late) FILTER (WHERE due)                             AS avg_days_late_all_due,
        COUNT(*) FILTER (WHERE complete)                              AS completed_lines,
        STDDEV_SAMP(lead_time_days) FILTER (WHERE complete)           AS lead_time_sd_raw,
        SUM(received_qty) FILTER (WHERE NOT cancelled)                AS received_qty,
        SUM(rejected_qty) FILTER (WHERE NOT cancelled)                AS rejected_qty,
        SUM(line_value)   FILTER (WHERE NOT cancelled)                AS spend
    FROM v_syn_line_delivery
    GROUP BY supplier_id
),
c AS (
    SELECT
        m.*,
        CASE WHEN m.completed_lines >= p.min_completed_for_variability THEN m.lead_time_sd_raw END AS lead_time_sd,
        CASE WHEN m.received_qty > 0 THEN m.rejected_qty::DOUBLE / m.received_qty END AS reject_rate,
        CASE WHEN m.due_lines >= p.min_lines_ranked THEN 'Ranked'
             WHEN m.due_lines >= p.min_lines_provisional THEN 'Provisional'
             ELSE 'Insufficient evidence' END AS evidence_status
    FROM m CROSS JOIN p
),
s AS (
    SELECT
        c.*,
        LEAST(1, GREATEST(0, (c.otif_rate - p.otif_poor) / (p.otif_target - p.otif_poor))) * 100 AS score_otif,
        LEAST(1, GREATEST(0, (p.reject_rate_poor - c.reject_rate) / (p.reject_rate_poor - p.reject_rate_target))) * 100 AS score_quality,
        LEAST(1, GREATEST(0, (p.leadtime_sd_poor - c.lead_time_sd) / (p.leadtime_sd_poor - p.leadtime_sd_target))) * 100 AS score_leadtime_consistency,
        LEAST(1, GREATEST(0, (p.avg_days_late_poor - c.avg_days_late_all_due) / (p.avg_days_late_poor - p.avg_days_late_target))) * 100 AS score_lateness,
        p.weight_otif, p.weight_quality, p.weight_leadtime_consistency, p.weight_lateness
    FROM c CROSS JOIN p
),
w AS (
    SELECT
        s.*,
        COALESCE(score_otif * weight_otif, 0) + COALESCE(score_quality * weight_quality, 0)
          + COALESCE(score_leadtime_consistency * weight_leadtime_consistency, 0)
          + COALESCE(score_lateness * weight_lateness, 0) AS weighted_points,
        (CASE WHEN score_otif IS NOT NULL THEN weight_otif ELSE 0 END)
          + (CASE WHEN score_quality IS NOT NULL THEN weight_quality ELSE 0 END)
          + (CASE WHEN score_leadtime_consistency IS NOT NULL THEN weight_leadtime_consistency ELSE 0 END)
          + (CASE WHEN score_lateness IS NOT NULL THEN weight_lateness ELSE 0 END) AS weight_used
    FROM s
),
f AS (
    SELECT
        w.*,
        CASE WHEN evidence_status = 'Insufficient evidence' OR weight_used = 0 THEN NULL
             ELSE ROUND(weighted_points / weight_used, 1) END AS performance_score
    FROM w
)
SELECT
    f.*,
    CASE WHEN evidence_status = 'Ranked'
         THEN RANK() OVER (PARTITION BY evidence_status = 'Ranked' ORDER BY performance_score DESC) END AS score_rank
FROM f;
