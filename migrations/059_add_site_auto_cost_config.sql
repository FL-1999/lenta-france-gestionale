ALTER TABLE sites ADD COLUMN labor_cost_per_person FLOAT NOT NULL DEFAULT 0;
ALTER TABLE sites ADD COLUMN material_unit_prices TEXT;
ALTER TABLE sites ADD COLUMN auto_cost_materials_enabled BOOLEAN NOT NULL DEFAULT 1;
ALTER TABLE sites ADD COLUMN auto_cost_labor_enabled BOOLEAN NOT NULL DEFAULT 1;
ALTER TABLE sites ADD COLUMN manual_material_entries_override_auto BOOLEAN NOT NULL DEFAULT 1;
