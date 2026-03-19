ALTER TABLE site_labor_cost_entries ADD COLUMN is_weekend BOOLEAN NOT NULL DEFAULT 0;
ALTER TABLE site_labor_cost_entries ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1;

UPDATE site_labor_cost_entries
SET
    is_weekend = CASE
        WHEN CAST(strftime('%w', work_date) AS INTEGER) IN (0, 6) THEN 1
        ELSE 0
    END,
    is_active = CASE
        WHEN CAST(strftime('%w', work_date) AS INTEGER) IN (0, 6) THEN 0
        ELSE 1
    END,
    total_cost = CASE
        WHEN CAST(strftime('%w', work_date) AS INTEGER) IN (0, 6) THEN 0
        ELSE COALESCE(worker_count, 0) * COALESCE(unit_cost, 0)
    END;
