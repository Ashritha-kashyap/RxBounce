-- Reporting views (used by Power BI)

CREATE OR REPLACE VIEW v_prescription_lines AS
SELECT pi.rx_item_id, p.rx_id, p.rx_date, p.patient_id, p.doctor_id, s.spec_name, d.dept_name,
       dr.drug_id, dr.drug_name, dr.subcat, dr.abc_class, pi.qty_requested, pi.qty_dispensed,
       pi.status, pi.bounce_reason,
       CASE WHEN pi.status IN ('Bounced','Partial') THEN 1 ELSE 0 END AS is_bounce,
       (pi.qty_requested - pi.qty_dispensed) * dr.unit_mrp AS lost_revenue
FROM prescription_items pi
JOIN prescriptions p   ON p.rx_id = pi.rx_id
JOIN drugs dr          ON dr.drug_id = pi.drug_id
LEFT JOIN specialisations s ON s.spec_id = p.spec_id
LEFT JOIN departments d     ON d.dept_id = s.dept_id;

CREATE OR REPLACE VIEW v_bounce_monthly AS
SELECT DATE_FORMAT(rx_date, '%Y-%m') AS month, dept_name,
       COUNT(*) AS total_lines, SUM(is_bounce) AS bounced_lines,
       SUM(is_bounce) / COUNT(*) AS bounce_rate, SUM(lost_revenue) AS lost_revenue
FROM v_prescription_lines
GROUP BY DATE_FORMAT(rx_date, '%Y-%m'), dept_name;

CREATE OR REPLACE VIEW v_inventory_status AS
SELECT dr.drug_id, dr.drug_name, dr.abc_class, s.qty_on_hand, s.on_order_qty,
       rp.reorder_point, rp.suggested_order_qty, rp.stockout_risk, rp.risk_band,
       s.qty_on_hand * dr.unit_cost AS stock_value
FROM stock_on_hand s
JOIN drugs dr ON dr.drug_id = s.drug_id
LEFT JOIN reorder_policy rp ON rp.drug_id = s.drug_id;
