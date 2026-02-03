UPDATE machines
SET machine_type_id = (
    SELECT machine_types.id
    FROM machine_types
    WHERE machine_types.code = machines.machine_type
)
WHERE machine_type IS NOT NULL
  AND machine_type_id IS NULL;

SELECT changes() AS backfilled_rows;
