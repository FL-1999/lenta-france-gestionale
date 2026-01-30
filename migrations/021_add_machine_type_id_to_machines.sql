ALTER TABLE machines
ADD COLUMN machine_type_id INTEGER REFERENCES machine_types(id);

UPDATE machines
SET machine_type_id = (
    SELECT machine_types.id
    FROM machine_types
    WHERE machine_types.code = machines.machine_type
)
WHERE machine_type IS NOT NULL;

SELECT changes() AS backfilled_rows;
