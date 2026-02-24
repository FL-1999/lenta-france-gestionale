ALTER TABLE depots ADD COLUMN IF NOT EXISTS city VARCHAR(120);
ALTER TABLE depots ADD COLUMN IF NOT EXISTS zip_code VARCHAR(20);
ALTER TABLE depots ADD COLUMN IF NOT EXISTS province VARCHAR(120);
ALTER TABLE depots ADD COLUMN IF NOT EXISTS country VARCHAR(120);

INSERT INTO depots (name, address, city, zip_code, province, country, is_active)
SELECT 'Dépôt Paris Nord', '12 Rue de la République', 'Paris', '75010', 'Île-de-France', 'France', 1
WHERE NOT EXISTS (SELECT 1 FROM depots WHERE name = 'Dépôt Paris Nord');

INSERT INTO depots (name, address, city, zip_code, province, country, is_active)
SELECT 'Dépôt Lyon Est', '45 Avenue Jean Jaurès', 'Lyon', '69007', 'Rhône', 'France', 1
WHERE NOT EXISTS (SELECT 1 FROM depots WHERE name = 'Dépôt Lyon Est');

INSERT INTO depots (name, address, city, zip_code, province, country, is_active)
SELECT 'Dépôt Marseille Sud', '8 Boulevard Michelet', 'Marseille', '13008', 'Bouches-du-Rhône', 'France', 1
WHERE NOT EXISTS (SELECT 1 FROM depots WHERE name = 'Dépôt Marseille Sud');
