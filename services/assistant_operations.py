"""Reuse validated business operations, with caller-owned transactions and real previews."""
from datetime import datetime, timedelta
import hashlib
import json
from uuid import uuid4

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from models import (AssistantProposal, Fiche, FleetJourney, Personale, PersonalePresenza,
                    Report, Site, User)
from audit_utils import log_audit_event
from services.assistant_schemas import INPUTS, ProposalInput
from services.assistant_security import settings


def canonical(value):
    return json.dumps(jsonable_encoder(value), sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def fields(obj, names):
    return jsonable_encoder({name: getattr(obj, name) for name in names.split()})


FICHE_FIELDS = ('date numero_pannello panel_name site_id coupe_id machine_id capocantiere_id '
    'operator hours description notes tipologia_scavo materiale profondita_totale diametro_palo '
    'larghezza_pannello altezza_pannello data_getto metri_cubi_gettati quota_ngf_testa quota_ngf_fondo '
    'quota_ngf_note quota_tn quota_partenza quota_testa_getto scavo_da_tn type_beton type_coulage '
    'terreno_teorico sonic_previsto sonic_realizzato inclinometre_previsto inclinometre_realizzato '
    'courbe_beton_active courbe_beton_realisee courbe_beton_tube courbe_beton_volume_total '
    'courbe_beton_hauteur_initiale courbe_beton_hauteur_finale')


def active_site(db, ident):
    site = db.query(Site).filter_by(id=ident).with_for_update().populate_existing().first()
    if not site or not site.is_active or getattr(site.status, 'value', site.status) == 'chiuso':
        raise HTTPException(409, 'Cantiere inesistente, disattivato o chiuso')
    return site


def perform(db, user, kind, raw, operation_id):
    """Never commits. Returns stable review data plus a result reference."""
    payload = INPUTS[kind].model_validate(raw)
    if kind == 'fiche.create':
        from main import _create_validated_fiche
        from models import Machine
        site = active_site(db, payload.cantiere_id)
        if payload.macchinario_id:
            machine = db.get(Machine, payload.macchinario_id)
            if not machine or not machine.is_active:
                raise HTTPException(422, 'Macchinario non attivo')
        lengths = [len(payload.strato_da), len(payload.strato_a), len(payload.strato_materiale)]
        if len(set(lengths)) != 1:
            raise HTTPException(422, 'Gli elenchi degli strati devono avere la stessa lunghezza')
        if payload.strato_materiale_altro and len(payload.strato_materiale_altro) != lengths[0]:
            raise HTTPException(422, 'Materiali personalizzati non allineati agli strati')
        for prefix in ('realisee', 'tube'):
            if len(getattr(payload, f'courbe_{prefix}_volume')) != len(getattr(payload, f'courbe_{prefix}_hauteur')):
                raise HTTPException(422, 'Punti della curva non allineati')
        fiche = _create_validated_fiche(db, current_user=user, commit=False, **payload.model_dump())
        machine = db.get(Machine, fiche.machine_id) if fiche.machine_id else None
        supervisor = db.get(User, fiche.capocantiere_id) if fiche.capocantiere_id else None
        summary = {'Operazione': 'Creazione fiche', 'Cantiere': site.name,
            'Macchinario': machine.name if machine else None,
            'Capocantiere': (supervisor.full_name or supervisor.email) if supervisor else None,
            'Dati registrati (lunghezze in metri, volumi in m³)': fields(fiche, FICHE_FIELDS),
            'Stratigrafia': [fields(layer, 'da_profondita a_profondita materiale') for layer in fiche.stratigrafie],
            'Effetti': 'Crea la fiche, aggiorna gli avanzamenti e le notifiche previste dal gestionale.'}
        return summary, dict(id=fiche.id, type='fiche', url=f'/manager/fiches/{fiche.id}')
    if kind == 'report.create':
        from routers.reports import ReportCreate, create_report_record
        site = active_site(db, payload.site_id)
        ids = [w.personale_id for w in payload.workers]
        # Creation must never silently overwrite an existing attendance, even on the same site.
        people = db.query(Personale).filter(Personale.id.in_(ids)).order_by(Personale.id).with_for_update().all()
        existing = db.query(PersonalePresenza).filter(
            PersonalePresenza.personale_id.in_(ids), PersonalePresenza.attendance_date == payload.date,
        ).first()
        if existing:
            raise HTTPException(409, 'Presenze già registrate per uno degli operai in questa data; verificare il rapportino esistente')
        data = payload.model_dump()
        data.update(site_name_or_code=site.name, workers_count=len(payload.workers))
        report = create_report_record(ReportCreate.model_validate(data), db, user, commit=False)
        names = {p.id: f'{p.nome} {p.cognome}' for p in people}
        summary = {'Operazione': 'Creazione rapportino giornaliero', 'Cantiere': site.name,
            'Data': str(payload.date), 'Ore rapportino': payload.total_hours,
            'Ore persona complessive': sum(w.hours_worked for w in payload.workers),
            'Personale': [dict(nome=names.get(w.personale_id), **w.model_dump()) for w in payload.workers],
            'Attività': payload.activities, 'Macchinari': payload.machines_used, 'Note': payload.notes,
            'Effetti': 'Crea il rapportino, registra le presenze e invia le notifiche interne previste.'}
        return summary, dict(id=report.id, type='report', url=f'/manager/rapportini/{report.id}')
    from routes.fleet import CreateInput, create_trip_record, validate_plan
    from models.veicoli import Veicolo
    from utils.places import get_selectable_places
    data = CreateInput.model_validate(dict(**payload.model_dump(), token=operation_id))
    route, moves, assets = validate_plan(db, data)
    result = create_trip_record(data, db, user, commit=False)
    places = {p.value: p.label for p in get_selectable_places(db)}
    driver, vehicle = db.get(User, payload.driver_id), db.get(Veicolo, payload.vehicle_id)
    summary = {'Operazione': 'Creazione trasporto programmato', 'Data': str(payload.day), 'Ora': str(payload.hour),
        'Autista': driver.full_name or driver.email, 'Camion': vehicle.targa,
        'Percorso': [places[p] for p in route],
        'Carichi': [dict(bene=assets[m['key']]['name'], origine=places[m['origin']],
                        destinazione=places[m['destination']], motivo=m['reason']) for m in moves],
        'Effetti': 'Prenota i beni e crea il viaggio. Non registra carichi/scarichi effettivi e non sposta le ubicazioni.'}
    return summary, dict(id=int(result['url'].rsplit('/', 1)[1]), type='trip', url=result['url'])


def preview(db, user, kind, payload, ident):
    nested = db.begin_nested()
    try:
        summary, _ = perform(db, user, kind, payload, ident)
        return jsonable_encoder(summary)
    finally:
        nested.rollback()


def prepare(db, user, body: ProposalInput):
    try:
        payload = INPUTS[body.kind].model_validate(body.payload).model_dump(mode='json')
    except ValidationError as exc:
        raise HTTPException(422, exc.errors(include_context=False, include_input=False))
    config = settings()
    previous = db.query(AssistantProposal).filter_by(owner_id=user.id, request_id=body.request_id).first()
    if previous:
        if previous.kind != body.kind or canonical(previous.payload) != canonical(payload) or previous.credential_hash != config.token_hash:
            raise HTTPException(409, 'request_id già usato con dati o credenziali differenti')
        return previous
    ident = uuid4().hex
    try:
        summary = preview(db, user, body.kind, payload, ident)
        proposal = AssistantProposal(id=ident, owner_id=user.id, credential_hash=config.token_hash,
            request_id=body.request_id, kind=body.kind, payload=payload, summary=summary,
            summary_hash=digest(summary), expires_at=datetime.utcnow() + timedelta(minutes=20))
        db.add(proposal)
        log_audit_event(db, user, 'assistant.proposed', 'integration', extra_data={'proposal_id': ident, 'kind': body.kind})
        db.commit()
        return proposal
    except IntegrityError:
        db.rollback()
        previous = db.query(AssistantProposal).filter_by(owner_id=user.id, request_id=body.request_id).first()
        if previous and previous.kind == body.kind and canonical(previous.payload) == canonical(payload) and previous.credential_hash == config.token_hash:
            return previous
        raise HTTPException(409, 'Dati cambiati o richiesta concorrente: ripetere la verifica')
    except Exception:
        db.rollback()
        raise


def decide(db, user, proposal, decision):
    if proposal.state != 'pending':
        return proposal  # Repeated browser submissions never repeat a business operation.
    ident, kind, payload, expected = proposal.id, proposal.kind, proposal.payload, proposal.summary_hash
    claimed = db.query(AssistantProposal).filter_by(id=ident, state='pending').filter(
        AssistantProposal.expires_at > datetime.utcnow(),
    ).update({'state': 'executing'}, synchronize_session=False)
    if claimed != 1:
        db.rollback()
        raise HTTPException(409, 'Proposta già elaborata o scaduta')
    try:
        if decision == 'approve':
            # Business changes, audit and consumption of approval share ONE transaction.
            summary, result = perform(db, user, kind, payload, ident)
            if digest(summary) != expected:
                raise HTTPException(409, 'I dati sono cambiati dopo l’anteprima. Preparare una nuova proposta.')
            state = 'applied'
        else:
            result, state = None, 'rejected'
        db.query(AssistantProposal).filter_by(id=ident).update(
            dict(state=state, result=result, decided_at=datetime.utcnow()), synchronize_session=False)
        log_audit_event(db, user, 'assistant.' + state, result['type'] if result else 'integration',
            target_id=result['id'] if result else None,
            extra_data={'proposal_id': ident, 'kind': kind, 'summary_hash': expected})
        db.commit()
        db.expire_all()
        return db.get(AssistantProposal, ident)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Conflitto con dati già registrati. Preparare una nuova proposta.')
    except Exception:
        db.rollback()
        raise
