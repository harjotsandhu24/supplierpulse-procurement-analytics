-- View: City of Austin PO lines in the focus window (complete fiscal years set in params),
-- enriched with vendor display name, category label and spend family.
-- Joins are many-to-one on unique dimension keys, so line count and spend are preserved.
CREATE OR REPLACE VIEW v_obs_focus_line AS
SELECT
    l.*,
    v.vendor_name,
    c.class_label,
    c.spend_family
FROM obs_po_line AS l
JOIN obs_vendor   AS v ON v.vendor_code = l.vendor_code
JOIN obs_category AS c ON c.nigp_class  = l.nigp_class
CROSS JOIN params AS p
WHERE l.fiscal_year BETWEEN p.focus_fy_start AND p.focus_fy_end;
