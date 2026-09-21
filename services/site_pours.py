"""Transactional grouping. Actual shared concrete is never counted twice."""
import json
import math
import re
from decimal import Decimal, ROUND_HALF_UP
from fastapi import HTTPException
from models import Site, Fiche, SitePour, SitePourPanel, SiteCoupeAssignment
from services.site_plan_project import approved_panels


def positive(value, label):
    if value is None or not math.isfinite(float(value)) or float(value) <= 0:
        raise HTTPException(400, f'Completa {label}: deve essere maggiore di zero.')
    return float(value)


def allocation(total, weights):
    amount = Decimal(str(positive(total, 'il volume totale'))).quantize(Decimal('.001'), rounding=ROUND_HALF_UP)
    if amount <= 0:
        raise HTTPException(400, 'Il volume minimo è 0,001 m³.')
    values = [Decimal(str(positive(w, 'le dimensioni dei pannelli'))) for w in weights]
    raw = [amount * w / sum(values) for w in values]
    # Largest remainder: 0.001 m³ precision and an exactly conserved total.
    from decimal import ROUND_DOWN
    parts = [v.quantize(Decimal('.001'), rounding=ROUND_DOWN) for v in raw]
    rest = int((amount - sum(parts)) * 1000)
    for i in sorted(range(len(parts)), key=lambda i: raw[i]-parts[i], reverse=True)[:rest]:
        parts[i] += Decimal('.001')
    return [float(v) for v in parts]


def group_for_panel(db, site_id, number):
    return db.query(SitePourPanel).filter_by(site_id=site_id, number=number).first()


def panel_fiches(db, site_id):
    result = {f.numero_pannello: f for f in db.query(Fiche).filter_by(site_id=site_id, tipologia_scavo='paratia')}
    for m in db.query(SitePourPanel).filter_by(site_id=site_id):
        if m.fiche is not None:
            result[m.number] = m.fiche
    return result


def create_group(db, site, numbers, kind, confirm_net):
    db.query(Site).filter_by(id=site.id).with_for_update().one()
    if kind not in ('angle', 'joint') or len(numbers) < 2 or len(numbers) > 20 or len(set(numbers)) != len(numbers):
        raise HTTPException(400, 'Seleziona da 2 a 20 pannelli distinti e il tipo di getto.')
    panels = {p['element']: p for p in approved_panels(db, site.id)}
    fiches = panel_fiches(db, site.id)
    members = []
    for n in sorted(numbers):
        p = panels.get(n)
        if not p:
            raise HTTPException(400, 'Seleziona pannelli della pianta convalidata.')
        if group_for_panel(db, site.id, n):
            raise HTTPException(409, 'Un pannello appartiene già a un getto. Apri o sciogli prima quel gruppo.')
        f = fiches.get(n)
        if kind == 'angle' and f:
            raise HTTPException(409, 'Configura l’angolo prima di compilare le fiches dei suoi pannelli.')
        a = db.query(SiteCoupeAssignment).filter_by(site_id=site.id, tipologia_scavo='paratia', numero_elemento=n).first()
        c = a.coupe if a else None
        if not c:
            raise HTTPException(400, f'Assegna prima una CUP a {p["label"]}.')
        snap = {'width': positive(f.larghezza_pannello if f else p.get('width_m'), 'la larghezza'),
                'depth': positive(f.profondita_totale if f else c.profondita_teorica, 'la profondità nella CUP'),
                'thickness': positive(f.altezza_pannello if f else c.spessore, 'lo spessore nella CUP'),
                'coupe_id': c.id, 'coupe': c.nome,
                'old_volume': f.metri_cubi_gettati if f else None,
                'old_date': f.data_getto.isoformat() if f and f.data_getto else None}
        members.append(SitePourPanel(site_id=site.id, number=n, label=p['label'], fiche=f, snapshot=json.dumps(snap)))
    label = ' + '.join(m.label for m in members)
    if kind == 'angle':
        names = [re.fullmatch(r'(.+?)\s*([ab])', m.label.strip(), re.I) for m in members]
        if len(members) != 2 or not all(names) or names[0][1].strip().casefold() != names[1][1].strip().casefold() or {m[2].lower() for m in names} != {'a','b'}:
            raise HTTPException(400, 'Un angolo richiede due pannelli A e B con lo stesso numero, per esempio P7A e P7B.')
        if not confirm_net:
            raise HTTPException(400, 'Conferma che le larghezze dei due bracci non contino due volte l’intersezione.')
        snapshots = [json.loads(m.snapshot) for m in members]
        if len({s['coupe_id'] for s in snapshots}) != 1:
            raise HTTPException(400, 'Per la fiche unica assegna ai due bracci la stessa CUP; le larghezze restano distinte.')
        label = names[0][1].strip() + ' A/B'
    group = SitePour(site_id=site.id, kind=kind, label=label, members=members)
    db.add(group); db.flush()
    return group


def before_fiche_save(db, fiche, updating=False):
    """Called before commit by both ordinary fiche workflows."""
    existing = list(fiche.pour_panels) if updating else []
    member = group_for_panel(db, fiche.site_id, fiche.numero_pannello) if fiche.tipologia_scavo == 'paratia' else None
    if existing and (not member or member.pour_id != existing[0].pour_id):
        raise HTTPException(409, 'Sciogli il raggruppamento prima di cambiare cantiere o pannello della fiche.')
    if not member:
        return
    group = member.pour
    db.query(Site).filter_by(id=fiche.site_id).with_for_update().one()
    if group.kind == 'angle':
        current = next((m.fiche for m in group.members if m.fiche is not None), None)
        if current and current.id != fiche.id:
            raise HTTPException(409, 'L’angolo ha già una fiche unica: apri quella esistente.')
        snaps = [json.loads(m.snapshot) for m in group.members]
        # The one fiche represents the developed, net width of both arms.
        if fiche.coupe_id != snaps[0]['coupe_id']:
            raise HTTPException(400, 'La fiche dell’angolo deve usare la CUP dei due bracci.')
        fiche.panel_name = group.label
        fiche.larghezza_pannello = sum(s['width'] for s in snaps)
        group.total_m3 = fiche.metri_cubi_gettati
        group.cast_date = fiche.data_getto
        for m in group.members:
            m.fiche = fiche
            m.allocated_m3 = None  # one actual quantity for the entire angle
    else:
        if group.total_m3 is not None:
            if fiche.metri_cubi_gettati != member.allocated_m3 or fiche.data_getto != group.cast_date:
                raise HTTPException(409, 'Modifica volume e data dal getto congiunto nella pagina del cantiere.')
            snap = json.loads(member.snapshot)
            if any(abs((getattr(fiche, field) or 0)-snap[key]) > .00001 for field,key in (
                    ('larghezza_pannello','width'),('profondita_totale','depth'),('altezza_pannello','thickness'))):
                raise HTTPException(409, 'Sciogli prima il getto per modificare le dimensioni usate nella ripartizione.')
            if fiche.courbe_beton_active or fiche.courbe_beton_volume_total is not None:
                raise HTTPException(409, 'La quantità è gestita dal getto congiunto; non aggiungere una curva individuale.')
        else:
            snap = json.loads(member.snapshot)
            snap.update(width=positive(fiche.larghezza_pannello,'la larghezza'), depth=positive(fiche.profondita_totale,'la profondità'), thickness=positive(fiche.altezza_pannello,'lo spessore'))
            member.snapshot=json.dumps(snap)
        member.fiche = fiche
    group.revision += 1


def record_joint(db, group, total, cast_date, manual=None):
    if group.kind != 'joint':
        raise HTTPException(400, 'Il calcestruzzo dell’angolo si registra nella fiche unica.')
    if not all(m.fiche is not None for m in group.members):
        raise HTTPException(400, 'Compila prima le fiches dei pannelli: poi registra qui il totale del getto.')
    weights = []
    for m in group.members:
        f = m.fiche
        if f.courbe_beton_active or f.courbe_beton_volume_total is not None:
            raise HTTPException(400, 'Rimuovi la curva di getto individuale prima di ripartire un getto comune.')
        s = json.loads(m.snapshot)
        s.update(width=positive(f.larghezza_pannello,'la larghezza'), depth=positive(f.profondita_totale,'la profondità'), thickness=positive(f.altezza_pannello,'lo spessore'))
        if group.total_m3 is None:
            s.update(old_volume=f.metri_cubi_gettati, old_date=f.data_getto.isoformat() if f.data_getto else None)
        m.snapshot = json.dumps(s)
        weights.append(s['width']*s['depth']*s['thickness'])
    parts = allocation(total, weights)
    if manual is not None:
        if len(manual) != len(parts) or any(not math.isfinite(v) or v < 0 for v in manual):
            raise HTTPException(400, 'Quantità individuali non valide.')
        parts = [float(Decimal(str(v)).quantize(Decimal('.001'), rounding=ROUND_HALF_UP)) for v in manual]
        if sum(Decimal(str(v)) for v in parts) != Decimal(str(total)).quantize(Decimal('.001'), rounding=ROUND_HALF_UP):
            raise HTTPException(400, 'La somma delle quantità deve coincidere con il totale del getto.')
    for m, value in zip(group.members, parts):
        m.allocated_m3 = value
        m.fiche.metri_cubi_gettati = value
        m.fiche.data_getto = cast_date
    group.total_m3 = float(Decimal(str(total)).quantize(Decimal('.001'), rounding=ROUND_HALF_UP))
    group.cast_date = cast_date
    group.revision += 1


def describe(group):
    return {'id':group.id, 'kind':group.kind, 'label':group.label, 'revision':group.revision,
            'total_m3':group.total_m3, 'cast_date':group.cast_date.isoformat() if group.cast_date else None,
            'members':[{'number':m.number,'label':m.label,'fiche_id':m.fiche_id,'allocated_m3':m.allocated_m3,
                        **json.loads(m.snapshot)} for m in group.members]}


def completed_numbers(fiches, total):
    numbers=set()
    for f in fiches:
        if f.tipologia_scavo != 'paratia': continue
        numbers.add(f.numero_pannello)
        numbers.update(m.number for m in getattr(f,'pour_panels',[]))
    return {n for n in numbers if n and 1 <= n <= total}
