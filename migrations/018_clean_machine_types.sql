UPDATE machines
SET machine_type = NULL
WHERE machine_type IS NOT NULL
  AND machine_type NOT IN (
    'macchina base su cingoli',
    'pala gommata',
    'scavatore',
    'gru cingolata',
    'kelly per diaframmi',
    'macchina operatrice diaframmi',
    'macchina operatrice pali',
    'gruppo elettrogeno',
    'dissabbiatore',
    'miscelatore',
    'pompa bentonite',
    'pompa acqua',
    'saldatrice',
    'taglia asfalto'
  );

SELECT changes() AS cleaned_rows;
