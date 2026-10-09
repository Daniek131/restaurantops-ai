-- Run against the SQLAlchemy-created schema. Values use each ingredient's unit.
-- Low stock and suggested quantity to return to the configured target.
SELECT i.id, i.name, i.unit, i.on_hand, v.name AS vendor,
       i.target_level - i.on_hand AS reorder_quantity
FROM ingredients AS i
LEFT JOIN vendors AS v ON v.id = i.vendor_id
WHERE i.on_hand <= i.par_level
ORDER BY i.id;

-- Historical standard-cost COGS. Do not join current ingredient prices here.
SELECT ingredient_id, SUM(-quantity) AS units_used,
       SUM(-quantity * unit_cost) AS cogs
FROM stock_movements
WHERE kind = 'sale'
GROUP BY ingredient_id;

-- PostgreSQL daily usage, in UTC. This aggregate only includes days with sales;
-- app/analytics.py fills missing calendar days for the baseline forecast.
SELECT ingredient_id, DATE(occurred_at AT TIME ZONE 'UTC') AS day,
       SUM(-quantity) AS usage
FROM stock_movements
WHERE kind = 'sale'
GROUP BY ingredient_id, DATE(occurred_at AT TIME ZONE 'UTC')
ORDER BY ingredient_id, day;
