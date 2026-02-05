UPDATE machine_types
SET is_active = 1
WHERE is_active IS NULL
   OR is_active = 0;

SELECT changes() AS reactivated_rows;
