"""Section drawing proposals and reviewed metadata. Never infer butons from colour.

Only explicit labels are interpreted. Extraction is confined to the selected page
and crop; multiple section titles or contradictory values require manual review.
"""
from io import BytesIO
import base64
import json
import math
import re
import unicodedata

from services.site_plan_import import MAX_PDF_BYTES, _PDF_RENDER_LOCK

NUMBER = r"[+\-]?\d+(?:[.,]\d+)?"
LABELS = dict(quota_tn='TN', quota_testa='Tête de paroi', spessore='Épaisseur',
              base_paroi_mecanique='Base mécanique', quota_fondo_teorica='Base hydraulique',
              mechanical='Hauteur mécanique', total='Hauteur totale')


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKD', text.lower())
                   if not unicodedata.combining(c)).replace('−', '-').replace('–', '-')


def decimal(value):
    return float(value.replace(',', '.'))


def parse_lines(lines):
    """lines are text runs with top-left PDF coordinates, in the selected region."""
    fields, warnings, evidence = {}, [], []
    candidates = {}
    titles, struts = set(), []
    treatment = {'state': 'unknown', 'top': None, 'bottom': None}
    dimensions = {}

    def collect(key, value, source):
        candidates.setdefault(key, set()).add(value)
        evidence.append({'field': key, 'value': value, 'text': source[:240]})

    for line in lines:
        raw = line['text']; text = normalized(raw)
        for title in re.findall(r'\bcoupe\s*([0-9]+[a-z]?)\b', text):
            titles.add(title)
        for key, pattern in (
            ('quota_tn', rf'\b(?:tn|terrain naturel)\s*[:=]?\s*({NUMBER})\s*(?:m\s*)?ngf'),
            ('quota_testa', rf'\btete\s+(?:pm|paroi(?:s)?(?: moulee?)?)\b[^+\d\-]{{0,45}}({NUMBER})\s*(?:m\s*)?ngf'),
            ('base_paroi_mecanique', rf'\bbase\s+(?:pm|paroi(?:s)?)\s+mecanique\s*[:=]?\s*({NUMBER})\s*(?:m\s*)?ngf'),
            ('quota_fondo_teorica', rf'\bbase\s+(?:pm|paroi(?:s)?)\s+hydraulique\s*[:=]?\s*({NUMBER})\s*(?:m\s*)?ngf'),
        ):
            for match in re.finditer(pattern, text):
                collect(key, decimal(match[1]), raw)
        for key, pattern in (
            ('mechanical', rf'\bht\.?\s*[:=]\s*({NUMBER})\s*m\b'),
            ('total', rf'\bhtot\.?\s*[:=]\s*({NUMBER})\s*m\b'),
            ('spessore', rf'\bep\.?\s*[:=]\s*({NUMBER})\s*m\b'),
        ):
            for match in re.finditer(pattern, text):
                collect(key, decimal(match[1]), raw)
        # Plain Base PM is only resolved against the explicitly quoted heights.
        for match in re.finditer(rf'\bbase\s+pm\s*[:=]?\s*({NUMBER})\s*ngf', text):
            collect('base_candidate', decimal(match[1]), raw)
        # An excavation elevation or an unlabelled blue line is never a buton.
        if re.search(r'\baxe\s+(?:du\s+|de\s+|des\s+)?butons?\b', text):
            values = re.findall(rf'({NUMBER})\s*(?:m\s*)?ngf\b', text)
            if len(values) == 1:
                struts.append(decimal(values[0]))
                evidence.append({'field': 'strut', 'value': struts[-1], 'text': raw[:240]})
            else:
                warnings.append('Asse puntone senza quota NGF univoca / Axe du buton sans cote NGF univoque.')
        if re.search(r'traitement\s+(?:de\s+)?permeabilite', text):
            treatment['state'] = 'present'
            values = re.findall(rf'({NUMBER})\s*(?:m\s*)?ngf\b', text)
            # Only an explicitly written interval on the treatment annotation is used.
            if len(values) == 2:
                treatment.update(top=max(map(decimal, values)), bottom=min(map(decimal, values)))
            elif len(values) == 1:
                treatment['top'] = decimal(values[0])

    if len(titles) > 1:
        return {'fields': {}, 'struts': [], 'treatment': {'state': 'unknown'}, 'evidence': [],
                'warnings': ['Più coupe nella selezione: ritaglia una sola coupe / Plusieurs coupes : sélectionnez une seule coupe.'],
                'blocked': True}
    if titles:
        fields['nome'] = 'Coupe ' + next(iter(titles)).upper()
    for key, values in candidates.items():
        if key == 'base_candidate':
            continue
        if len(values) != 1:
            warnings.append(f'{LABELS.get(key, key)}: valori discordanti, da compilare / {LABELS.get(key, key)} : valeurs contradictoires, à compléter.')
            continue
        value = next(iter(values))
        if key in ('mechanical', 'total'):
            dimensions[key] = value
        else:
            fields[key] = value
    head = fields.get('quota_testa')
    for dimension, key in [('mechanical', 'base_paroi_mecanique'), ('total', 'quota_fondo_teorica')]:
        height = dimensions.get(dimension)
        if head is not None and height is not None and height > 0:
            derived = round(head-height, 6)
            explicit = fields.get(key)
            bases = candidates.get('base_candidate', set())
            if (explicit is not None and abs(explicit-derived) > .02) or (bases and not any(abs(v-derived) <= .02 for v in bases)):
                fields.pop(key, None)
                warnings.append(f'{LABELS[key]}: altezza e quota non coincidono / {LABELS[key]} : hauteur et cote incohérentes.')
            elif len(candidates.get(key, set())) <= 1:
                fields[key] = derived
                evidence.append({'field': key, 'value': derived, 'text': f'Tête {head:g} − H {height:g}'})
    if fields.get('quota_tn') is not None and fields.get('quota_fondo_teorica') is not None:
        fields['profondita_teorica'] = round(fields['quota_tn']-fields['quota_fondo_teorica'], 6)
    if treatment['state'] == 'present' and treatment['top'] is None:
        warnings.append('Trattamento presente: controlla le quote sul disegno / Traitement présent : renseignez les cotes du dessin.')
    if not struts:
        warnings.append('Nessun asse puntone identificato: controlla e aggiungi i livelli mancanti / Aucun axe de buton identifié : vérifiez et ajoutez les niveaux manquants.')
    if not lines:
        warnings.append('PDF senza testo leggibile: compila dal disegno / PDF sans texte lisible : renseignez les valeurs depuis le dessin.')
    for key in ('quota_tn', 'quota_testa', 'quota_fondo_teorica', 'base_paroi_mecanique', 'spessore'):
        if key not in fields:
            warnings.append(f'{LABELS[key]}: non identificato / {LABELS[key]} : non identifié.')
    return dict(fields=fields, struts=sorted(set(struts), reverse=True), treatment=treatment,
                evidence=evidence, warnings=warnings, blocked=not bool(fields or struts or treatment['state']=='present'), dimensions=dimensions)


def read_pdf(data, page_number=1, crop=None):
    import pdfplumber
    import pypdfium2 as pdfium
    if not data.startswith(b'%PDF') or len(data) > MAX_PDF_BYTES:
        raise ValueError('Seleziona un PDF di massimo 15 MB / Choisissez un PDF de 15 Mo maximum.')
    if crop is not None:
        if not isinstance(crop, list) or len(crop) != 4 or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in crop):
            raise ValueError('Selezione non valida / Sélection invalide.')
        if crop[2]-crop[0] < .01 or crop[3]-crop[1] < .01:
            raise ValueError('Selezione troppo piccola / Sélection trop petite.')
    try:
        with pdfplumber.open(BytesIO(data)) as pdf:
            count = len(pdf.pages)
            if not 1 <= page_number <= count:
                raise ValueError('Pagina non presente / Page inexistante.')
            page = pdf.pages[page_number-1]
            width, height = float(page.width), float(page.height)
            if not 0 < min(width, height) or max(width, height) > 15000 or len(page.chars) > 50000:
                raise ValueError('Pagina troppo complessa / Page trop complexe.')
            if crop:
                x0, y0, _, _ = page.bbox
                page = page.crop((x0+crop[0]*width, y0+crop[1]*height, x0+crop[2]*width, y0+crop[3]*height))
            lines = page.extract_text_lines(layout=False, strip=True, return_chars=False)
            result = parse_lines(lines)
        with _PDF_RENDER_LOCK, pdfium.PdfDocument(data) as pdf:
            page = pdf[page_number-1]
            try:
                bitmap = page.render(scale=min(2, 1800/max(width, height)))
                try:
                    out = BytesIO(); bitmap.to_pil().save(out, format='PNG')
                finally:
                    bitmap.close()
            finally:
                page.close()
        return {**result, 'page_count': count, 'preview': base64.b64encode(out.getvalue()).decode('ascii')}
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('PDF non leggibile o protetto / PDF illisible ou protégé.') from exc


def validate_info(raw):
    if not raw:
        return None
    if len(raw) > 12000:
        raise ValueError('Informazioni coupe troppo lunghe / Informations trop longues.')
    try:
        value = json.loads(raw)
        if not isinstance(value, dict) or value.get('reviewed') is not True:
            raise ValueError('Controlla e conferma i dati letti / Vérifiez et confirmez les données lues.')
        struts = value.get('struts', [])
        if not isinstance(struts, list) or len(struts) > 30:
            raise ValueError()
        def number(v):
            if type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 10000:
                raise ValueError()
            return round(float(v), 4)
        struts = [number(v) for v in struts]
        if len(set(struts)) != len(struts):
            raise ValueError('Due livelli hanno la stessa quota / Deux niveaux ont la même cote.')
        treatment = value.get('treatment', {})
        state = treatment.get('state', 'unknown')
        if state not in ('unknown', 'present', 'absent'):
            raise ValueError()
        top, bottom = treatment.get('top'), treatment.get('bottom')
        if state == 'present':
            top = number(top)
            bottom = number(bottom) if bottom is not None else None
            if bottom is not None and bottom > top:
                raise ValueError('Il limite inferiore supera quello superiore / La cote basse dépasse la cote haute.')
        else:
            top = bottom = None
        source = value.get('source') or {}
        filename = str(source.get('filename', ''))[:255]
        page = source.get('page', 1)
        if type(page) is not int or page < 1:
            raise ValueError()
        return dict(reviewed=True, struts=sorted(struts, reverse=True),
                    treatment=dict(state=state, top=top, bottom=bottom),
                    source=dict(filename=filename, page=page))
    except (TypeError, AttributeError, KeyError, json.JSONDecodeError) as exc:
        raise ValueError('Controlla puntoni e trattamento / Vérifiez les butons et le traitement.') from exc
