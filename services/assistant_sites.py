"""Bounded site patches with before/after previews; no commits or generic ORM writes."""
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from models import Site, User, RoleEnum
from audit_utils import log_audit_event
from services.assistant_schemas import SiteDetailsChanges
from services.site_works import guide_configuration

PROGRESS_FIELDS = ('cordoli_total_m', 'cordoli_done_m', 'installazione_cantiere_pct',
                   'pozzi_pompaggio_pct', 'rabotage_pct')
DETAIL_FIELDS = tuple(SiteDetailsChanges.model_fields)
LABELS = {
    'cordoli_total_m': 'Muretti guida — totale manuale (m; vuoto = da pianta)',
    'cordoli_done_m': 'Muretti guida — metri eseguiti complessivi',
    'installazione_cantiere_pct': 'Installazione cantiere (%)',
    'pozzi_pompaggio_pct': 'Pozzi pompaggio (%)', 'rabotage_pct': 'Rabotage (%)',
    'name': 'Nome cantiere', 'code': 'Codice cantiere', 'address': 'Indirizzo',
    'city': 'Città', 'country': 'Paese', 'lat': 'Latitudine', 'lng': 'Longitudine',
    'place_id': 'Riferimento geografico', 'start_date': 'Data inizio', 'end_date': 'Data fine',
    'caposquadra_id': 'Responsabile cantiere (ID)', 'projet_client': 'Cliente',
    'projet_maitre_oeuvre': 'Direzione lavori', 'projet_entreprise': 'Impresa',
    'projet_affaire': 'Affare', 'projet_indice': 'Indice progetto', 'projet_mission': 'Missione',
    'projet_redaction': 'Redazione', 'projet_controle': 'Controllo',
}


def values(site, names):
    return jsonable_encoder({key: getattr(site, key) for key in names})


def change_list(before, after):
    return [{'campo': key, 'descrizione': LABELS.get(key, key), 'prima': before[key], 'dopo': after[key]}
            for key in before if before[key] != after[key]]


def progress_context(db, site):
    from routes.site_works import snapshot
    revision, works, reference = snapshot(db, site)
    return {'configuration': guide_configuration(site), 'values': values(site, PROGRESS_FIELDS),
        'map_revision': revision,
        'reference': {k: reference[k] for k in ('plan_id', 'revision')} if reference else None,
        'manual_wells_allowed': not bool(works['wells']),
        'manual_rabotage_allowed': not bool(reference)}


def perform_site_update(db, user, kind, payload):
    # Serialize assistant edits with fiche/site transactions, reading fresh values.
    site = db.query(Site).filter_by(id=payload.site_id).with_for_update().populate_existing().first()
    if not site or not site.is_active or getattr(site.status, 'value', site.status) == 'chiuso':
        raise HTTPException(409, 'Cantiere inesistente, disattivato o chiuso')
    name, code = site.name, site.code
    changes = payload.changes.model_dump(exclude_unset=True)
    if kind == 'site.progress.update':
        from routes.site_works import ProgressUpdate, apply_progress_update
        before = progress_context(db, site)
        if 'cordoli_increment_m' in changes:
            changes['cordoli_done_m'] = round((site.cordoli_done_m or 0) + changes.pop('cordoli_increment_m'), 6)
        apply_progress_update(db, site, ProgressUpdate.model_validate(changes), user)
        after = progress_context(db, site)
        if any(key.startswith('cordoli_') for key in changes):
            total, done = after['configuration']['guide_total_m'], after['configuration']['guide_done_m']
            if not total and done:
                raise HTTPException(422, 'Manca il totale previsto dei muretti guida: indicarlo o completare la pianta.')
            if done > total:
                raise HTTPException(422, 'I metri eseguiti superano il totale previsto. Verificare entrambi i valori.')
        diff = change_list(before['values'], after['values'])
        effect = 'Aggiorna subito gli avanzamenti del cantiere. La produzione da fiches resta soggetta alla sua verifica.'
    else:
        before = values(site, DETAIL_FIELDS + ('place_id',))
        for key in ('address', 'city', 'country'):
            if key in changes and changes[key] == '':
                changes[key] = None
        for key in DETAIL_FIELDS:
            if key.startswith('projet_') and changes.get(key) == '':
                changes[key] = None
        start = changes.get('start_date', site.start_date)
        end = changes.get('end_date', site.end_date)
        if start and end and end < start:
            raise HTTPException(422, 'La data di fine non può precedere la data di inizio.')
        if 'code' in changes and db.query(Site.id).filter(Site.code == changes['code'], Site.id != site.id).first():
            raise HTTPException(409, 'Codice cantiere già utilizzato.')
        responsible = None
        if changes.get('caposquadra_id') is not None:
            responsible = db.get(User, changes['caposquadra_id'])
            if not responsible or not responsible.is_active or responsible.role != RoleEnum.caposquadra:
                raise HTTPException(422, 'Selezionare un capocantiere attivo dal catalogo.')
        relocated = any(key in changes and changes[key] != getattr(site, key) for key in ('address', 'city', 'country'))
        if relocated or 'lat' in changes:
            has_address = changes.get('address', site.address)
            if has_address and changes.get('lat') is None and not payload.confirm_unverified_address:
                raise HTTPException(422, 'Indicare coordinate verificate oppure chiedere conferma per salvare l’indirizzo senza posizione sulla mappa.')
            if relocated and 'lat' not in changes:
                changes.update(lat=None, lng=None)
            changes['place_id'] = None  # Never preserve a geographic reference for a changed location.
        for key, value in changes.items():
            setattr(site, key, value)
        after = values(site, DETAIL_FIELDS + ('place_id',))
        diff = change_list(before, after)
        if responsible:
            for entry in diff:
                if entry['campo'] == 'caposquadra_id':
                    entry['responsabile'] = responsible.full_name or responsible.email
        log_audit_event(db, user, 'SITE_UPDATED', 'site', site.id, {'source': 'assistant', 'changes': diff})
        effect = 'Aggiorna i dati indicati del cantiere; gli altri dati e le fiches restano invariati.'
    if not diff:
        raise HTTPException(422, 'I valori indicati sono già registrati; nessuna modifica da salvare.')
    summary = {'Operazione': 'Aggiornamento avanzamento cantiere' if kind == 'site.progress.update' else 'Aggiornamento dati cantiere',
        'Cantiere': name, 'Codice': code, 'ID cantiere': site.id,
        'Modifiche': diff, 'Prima': before, 'Dopo': after, 'Effetti': effect}
    log_audit_event(db, user, 'ASSISTANT_SITE_PATCH', 'site', site.id, {'kind': kind, 'changes': diff})
    db.flush()
    return summary, {'id': site.id, 'type': 'site', 'changes': diff,
                     'url': f'/manager/cantieri/{site.id}/avanzamento' if kind == 'site.progress.update' else f'/manager/cantieri/{site.id}'}
