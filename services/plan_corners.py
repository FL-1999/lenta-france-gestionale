"""Reviewed plan corners retain two panel identities and one production fiche."""
import math
import re
from collections import defaultdict
from fastapi import HTTPException


def corner_name(panels):
    names = [re.fullmatch(r'(P\s*\d+)\s*([ab])', p['label'].strip(), re.I) for p in panels]
    if len(names) != 2 or not all(names):
        return None
    if names[0][1].replace(' ', '').casefold() != names[1][1].replace(' ', '').casefold():
        return None
    if {m[2].lower() for m in names} != {'a', 'b'}:
        return None
    return names[0][1].replace(' ', '') + ' A/B'


def groups(panels):
    result = defaultdict(list)
    for panel in panels:
        if panel.get('corner_group'):
            result[panel['corner_group']].append(panel)
    return result


def axes_angle(a, b):
    u = [a['points'][1][i]-a['points'][0][i] for i in (0, 1)]
    v = [b['points'][1][i]-b['points'][0][i] for i in (0, 1)]
    return abs(sum(x*y for x, y in zip(u, v)) / max(math.hypot(*u)*math.hypot(*v), 1e-9))


def overlap_area(subject, clip):
    """Convex polygon intersection; do not silently double-count the corner joint."""
    result = list(subject)
    sign = 1 if sum(a[0]*clip[(i+1)%4][1]-clip[(i+1)%4][0]*a[1] for i,a in enumerate(clip)) >= 0 else -1
    for i, a in enumerate(clip):
        b = clip[(i+1)%4]
        def side(p):
            return sign*((b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0]))
        incoming, result = result, []
        if not incoming:
            break
        prev = incoming[-1]
        for point in incoming:
            s, e = side(prev), side(point)
            if (s >= 0) != (e >= 0):
                ratio = s/(s-e)
                result.append([prev[j]+ratio*(point[j]-prev[j]) for j in (0, 1)])
            if e >= 0:
                result.append(point)
            prev = point
    return abs(sum(a[0]*result[(i+1)%len(result)][1]-result[(i+1)%len(result)][0]*a[1] for i,a in enumerate(result)))/2 if result else 0


def touching(a, b, tolerance):
    for i, x in enumerate(a):
        y = a[(i+1)%4]
        ux, uy = y[0]-x[0], y[1]-x[1]
        length = math.hypot(ux, uy)
        if not length:
            continue
        for j, c in enumerate(b):
            d = b[(j+1)%4]
            distances = [abs(ux*(p[1]-x[1])-uy*(p[0]-x[0]))/length for p in (c,d)]
            if max(distances) > tolerance:
                continue
            spans = sorted(((p[0]-x[0])*ux+(p[1]-x[1])*uy)/length for p in (c,d))
            if min(length, spans[1])-max(0, spans[0]) > tolerance:
                return True
    return False


def suggest_corners(panels):
    """Only unique adjacent A/B labels with transverse axes; never assume net widths."""
    names = defaultdict(list)
    for p in panels:
        m = re.fullmatch(r'(P\s*\d+)\s*[ab]', p['label'].strip(), re.I)
        if m:
            names[m[1].replace(' ', '').casefold()].append(p)
    for pair in names.values():
        if not corner_name(pair) or axes_angle(*pair) > .3:
            continue
        thickness = max(math.dist(p['points'][1], p['points'][2]) for p in pair)
        if min(math.dist(a,b) for a in pair[0]['points'] for b in pair[1]['points']) > thickness*1.5:
            continue
        for p in pair:
            p['corner_group'] = min(v['key'] for v in pair)
            p['corner_net_confirmed'] = False


def validate_corners(panels, scale, approve):
    for pair in groups(panels).values():
        label = corner_name(pair)
        if not label or axes_angle(*pair) > .97:
            raise HTTPException(400, 'Un angolo richiede due bracci A/B dello stesso numero e direzioni distinte.')
        if approve:
            tolerance = max(.02, (scale or 1)*.005)
            if overlap_area(pair[0]['points'], pair[1]['points']) > tolerance*tolerance:
                raise HTTPException(400, f'{label}: i bracci si sovrappongono. Correggi il raccordo prima della convalida.')
            if not touching(pair[0]['points'], pair[1]['points'], tolerance):
                raise HTTPException(400, f'{label}: accosta i bordi dei due bracci prima della convalida.')
            if not all(p.get('corner_net_confirmed') for p in pair):
                raise HTTPException(400, f'{label}: conferma le larghezze nette dei due bracci.')


def reconcile_groups(db, site, layout, previous=None):
    """Never rewrite a production fiche. Pending corners become groups after coupe setup."""
    import json
    from models import SitePour, SiteCoupeAssignment
    from services.site_pours import create_group
    new_pairs = {frozenset(p['element'] for p in pair): pair for pair in groups(layout['panels']).values()}
    old_pairs = {frozenset(p['element'] for p in pair) for pair in groups((previous or {}).get('panels', [])).values()}
    assignments = {a.numero_elemento: a.coupe for a in db.query(SiteCoupeAssignment).filter_by(site_id=site.id, tipologia_scavo='paratia')}
    production = db.query(SitePour).filter_by(site_id=site.id).all()
    for group in production:
        ids = frozenset(m.number for m in group.members)
        if ids not in old_pairs and ids not in new_pairs:
            continue
        pair = new_pairs.get(ids)
        same = pair and group.kind == 'angle' and group.label == corner_name(pair) and all(
            any(p['element'] == m.number and p['label'] == m.label and
                abs(p['width_m']-json.loads(m.snapshot)['width']) < 1e-6 for p in pair) for m in group.members)
        if same:
            cups = [assignments.get(m.number) for m in group.members]
            if any(m.fiche_id for m in group.members):
                if not all(cups) or any(c.id != json.loads(m.snapshot)['coupe_id'] for c, m in zip(cups, group.members)):
                    raise HTTPException(409, 'Un angolo con una fiche richiede che entrambi i bracci restino nella coupe originale.')
            elif not all(cups) or len({c.id for c in cups}) != 1 or not all(c.profondita_teorica and c.spessore for c in cups):
                db.delete(group)
            else:
                # Before production, keep dimensions in sync with the edited coupe.
                changed = False
                for member, coupe in zip(group.members, cups):
                    snap = json.loads(member.snapshot)
                    snap.update(coupe_id=coupe.id, coupe=coupe.nome, depth=coupe.profondita_teorica, thickness=coupe.spessore)
                    changed = changed or snap != json.loads(member.snapshot)
                    member.snapshot = json.dumps(snap)
                if changed:
                    group.revision += 1
            continue
        if any(m.fiche_id for m in group.members) or group.kind != 'angle':
            raise HTTPException(409, 'L’angolo ha già dati di produzione: gestisci prima il gruppo dalla pagina cantiere. Nessuna fiche è stata cancellata.')
        db.delete(group)
    db.flush()
    for ids, pair in new_pairs.items():
        cups = [assignments.get(n) for n in ids]
        if all(cups) and len({c.id for c in cups}) != 1:
            raise HTTPException(400, f'{corner_name(pair)}: assegna i due bracci alla stessa coupe per la fiche unica.')
        existing = db.query(SitePour).filter_by(site_id=site.id, kind='angle').all()
        if any(frozenset(m.number for m in g.members) == ids for g in existing):
            continue
        if all(cups) and all(c.profondita_teorica and c.spessore for c in cups):
            create_group(db, site, list(ids), 'angle', True, panels=layout['panels'])
