"""Stable panel identities shared by the approved plan, coupes and fiches."""
import json

from fastapi import HTTPException
from models import SitePlan, SiteProgressGridName, SiteCoupeAssignment, SiteSpecialEquipmentConfig, Fiche, Site


def approved_panels(db, site_id):
    plan = (db.query(SitePlan).filter(SitePlan.site_id == site_id, SitePlan.approved.isnot(None))
            .order_by(SitePlan.approved_at.desc(), SitePlan.id.desc()).first())
    return json.loads(plan.approved)['panels'] if plan else []


def panel_details(db, site_id, number, kind='paratia'):
    if kind == 'paratia':
        from models import SitePourPanel
        member = db.query(SitePourPanel).filter_by(site_id=site_id,number=number).first()
        if member and member.pour.kind == 'angle':
            return {'label':member.pour.label,'width_m':sum(json.loads(m.snapshot)['width'] for m in member.pour.members)}
    label = db.query(SiteProgressGridName).filter_by(
        site_id=site_id, tipologia_scavo=kind, numero_elemento=number).first()
    panel = next((p for p in approved_panels(db, site_id) if p.get('element') == number), None) if kind == 'paratia' else None
    if panel and panel.get('corner_group'):
        from services.plan_corners import corner_name
        pair = [p for p in approved_panels(db, site_id) if p.get('corner_group') == panel['corner_group']]
        if corner_name(pair):
            return {'label': corner_name(pair), 'width_m': sum(p['width_m'] for p in pair)}
    return {'label': label.nome_personalizzato if label else str(number),
            'width_m': panel.get('width_m') if panel else None}


def confirm_project_panels(db, site, layout, previous=None):
    # Serialize approvals of different PDF versions for the same site.
    db.query(Site).filter_by(id=site.id).with_for_update().one()
    labels = {r.numero_elemento: r for r in db.query(SiteProgressGridName).filter_by(site_id=site.id, tipologia_scavo='paratia')}
    used = set(labels)
    for model, field in ((Fiche, 'numero_pannello'), (SiteCoupeAssignment, 'numero_elemento'),
                         (SiteSpecialEquipmentConfig, 'numero_elemento')):
        used.update(getattr(r, field) for r in db.query(model).filter_by(site_id=site.id, tipologia_scavo='paratia'))
    for plan in db.query(SitePlan).filter(SitePlan.site_id == site.id, SitePlan.approved.isnot(None)):
        used.update(p['element'] for p in json.loads(plan.approved)['panels'] if p.get('element'))
    previous_by_key = {p['key']: p for p in (previous or {}).get('panels', [])}
    used.update(p['element'] for p in layout['panels'] if p.get('element'))
    candidate = 1
    for panel in layout['panels']:
        old = previous_by_key.get(panel['key'], {})
        if old.get('element') and panel.get('element') != old['element']:
            raise HTTPException(400, 'Il collegamento di un pannello già convalidato non può essere cambiato. Mantieni la sua identità.')
        if not panel.get('element'):
            while candidate in used:
                candidate += 1
            panel['element'] = candidate
            used.add(candidate)
        number = panel['element']
        label = labels.get(number)
        if label is None:
            label = SiteProgressGridName(site_id=site.id, tipologia_scavo='paratia', numero_elemento=number)
            db.add(label)
            labels[number] = label
        label.nome_personalizzato = panel['label']
    # Never remove or renumber existing production records.
    total = max(used, default=0)
    if not previous and not db.query(Fiche.id).filter_by(site_id=site.id, tipologia_scavo='paratia').first():
        total = max(total, len(layout['panels']))
    else:
        total = max(total, site.numero_totale_paratie or site.totale_paratie_da_scavare or 0)
    site.numero_totale_paratie = site.totale_paratie_da_scavare = site.paratie_total_panels = total
