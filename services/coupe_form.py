"""Validation and lossless redisplay of project coupe forms."""
import math
import re
from types import SimpleNamespace
from fastapi import HTTPException

FIELDS = ('nome descrizione_zona quota_tn quota_testa quota_fondo_teorica base_paroi_mecanique profondita_teorica scavo_da_tn quota_partenza_scavo quota_testa_getto_prevista type_beton type_coulage spessore larghezza diametro terreno_teorico note paratie pali armatura quota_reference_label').split()
NUMBERS = ('quota_tn quota_testa quota_fondo_teorica base_paroi_mecanique profondita_teorica quota_partenza_scavo quota_testa_getto_prevista spessore larghezza diametro').split()


def submitted_rows(payload):
    count = max((len(payload.get('coupe_'+f, [])) for f in ['id', *FIELDS]), default=0)
    def value(field, i):
        values=payload.get('coupe_'+field, [])
        return values[i] if i<len(values) else ''
    return [SimpleNamespace(**{f:value(f,i) for f in ['id',*FIELDS]}, submitted=True,
                            form_paratie=value('paratie',i),form_pali=value('pali',i),
                            delete_requested=value('id',i) in payload.get('delete_coupe_id',[])) for i in range(count)]


def validate_rows(payload, parse_numbers):
    errors=[]; owners={}
    for index,row in enumerate(submitted_rows(payload)):
        if row.delete_requested: continue
        significant=[f for f in FIELDS if f not in ('quota_reference_label','scavo_da_tn','type_coulage')]
        if not any(getattr(row,f).strip() for f in significant): continue
        name=row.nome or f'Coupe {index+1}'
        def error(field,it,fr): errors.append({'row':index,'field':'coupe_'+field,'name':name,'it':it,'fr':fr})
        values={}
        for field in NUMBERS:
            raw=getattr(row,field).strip()
            if not raw: values[field]=None; continue
            try:
                value=float(raw.replace(',','.'))
                if not math.isfinite(value): raise ValueError()
                values[field]=value
            except ValueError:
                values[field]=None
                error(field,'Inserisci un numero valido.','Saisissez un nombre valide.')
        for field in ('profondita_teorica','spessore','larghezza','diametro'):
            if values[field] is not None and values[field]<=0:
                error(field,'Il valore deve essere maggiore di zero.','La valeur doit être supérieure à zéro.')
        origin=values['quota_tn'] if row.scavo_da_tn!='0' else (values['quota_partenza_scavo'] if values['quota_partenza_scavo'] is not None else values['quota_testa'])
        bottom,depth=values['quota_fondo_teorica'],values['profondita_teorica']
        if origin is not None and bottom is not None:
            expected=round(origin-bottom,6)
            if expected<=0:
                error('quota_fondo_teorica','Il fondo deve essere sotto la quota di partenza.','Le fond doit être sous la cote de départ.')
            elif depth is not None and abs(expected-depth)>.02:
                error('profondita_teorica',f'Quote incoerenti: {origin:g} − {bottom:g} = {expected:g} m, non {depth:g} m.',f'Cotes incohérentes : {origin:g} − {bottom:g} = {expected:g} m, et non {depth:g} m.')
        if values['quota_tn'] is not None and values['quota_testa_getto_prevista'] is not None and values['quota_testa_getto_prevista']>values['quota_tn']:
            error('quota_testa_getto_prevista','La testa getto supera il TN.','La tête de bétonnage dépasse le TN.')
        if len(row.quota_reference_label)>30 or any(ord(c)<32 for c in row.quota_reference_label):
            error('quota_reference_label','Massimo 30 caratteri, senza interruzioni di riga.','30 caractères maximum, sans saut de ligne.')
        if len(row.armatura)>2000:
            error('armatura','Massimo 2000 caratteri.','2000 caractères maximum.')
        for field in ('paratie','pali'):
            try: numbers=parse_numbers(getattr(row,field))
            except (HTTPException, ValueError):
                error(field,'Associazione non valida: usa numeri o intervalli.','Affectation invalide : utilisez des numéros ou des intervalles.'); continue
            for number in numbers:
                key=(field,number)
                if key in owners:
                    error(field,f'Elemento {number} già selezionato in {owners[key]}.',f'Élément {number} déjà sélectionné dans {owners[key]}.')
                owners[key]=name
        previous=0
        for layer,line in enumerate(row.terreno_teorico.splitlines(),1):
            if not line.strip(): continue
            match=re.fullmatch(r'\s*([\d.,]+)\s*[-–]\s*([\d.,]+)\s*m?\s*:\s*(.*)',line)
            if not match:
                # Preserve historical descriptive geological notes.
                if re.match(r'\s*[\d.,]*\s*[-–]',line):
                    error('terreno_teorico',f'Strato {layer}: completa profondità e terreno.',f'Couche {layer} : complétez les profondeurs et le sol.')
                continue
            try: start,end=[float(v.replace(',','.')) for v in match.groups()[:2]]
            except ValueError:
                error('terreno_teorico',f'Strato {layer}: profondità non valide.',f'Couche {layer} : profondeurs invalides.');continue
            if not math.isfinite(start) or not math.isfinite(end) or start<0 or end<=start or abs(start-previous)>.01 or not match[3].strip():
                error('terreno_teorico',f'Strato {layer}: deve iniziare a {previous:g} m e finire più in basso; scegli il terreno.',f'Couche {layer} : commencez à {previous:g} m, terminez plus bas et choisissez le sol.')
            previous=end
    return errors
