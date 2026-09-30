"""Read-only validation issues, shared by preflight and final plan approval."""
import json
import math


def issue(panels, field, message, french=None, status=400):
    return {'keys': [p['key'] for p in panels], 'field': field,
            'message': message, 'french': french or message, 'status': status}


def project_issues(db, site, layout, previous=None):
    """Inspect existing identities, coupes and production without allocating or writing."""
    from models import SitePour, SiteCoupeAssignment, Fiche
    from services.plan_corners import groups, corner_name
    panels = layout['panels']
    old = {p['key']: p for p in (previous or {}).get('panels', [])}
    problems = []
    for p in panels:
        if old.get(p['key'], {}).get('element') and p.get('element') != old[p['key']]['element']:
            problems.append(issue([p], 'element', f"{p['label']}: mantieni il collegamento originale del pannello già convalidato.",
                                  f"{p['label']} : conservez le lien d’origine du panneau déjà validé."))
    # New, unallocated panels cannot have existing coupes or production records.
    new_pairs = {frozenset(p['element'] for p in pair): pair for pair in groups(panels).values()
                 if len(pair) == 2 and all(p.get('element') for p in pair)}
    old_pairs = {frozenset(p.get('element') for p in pair): pair
                 for pair in groups((previous or {}).get('panels', [])).values()}
    assignments = {a.numero_elemento: a.coupe for a in db.query(SiteCoupeAssignment).filter_by(site_id=site.id, tipologia_scavo='paratia')}
    production = db.query(SitePour).filter_by(site_id=site.id).all()
    retained = []
    for group in production:
        ids = frozenset(m.number for m in group.members)
        pair = new_pairs.get(ids)
        involved = pair or [p for p in panels if p.get('element') in ids] or old_pairs.get(ids, [])
        if ids not in old_pairs and ids not in new_pairs:
            retained.append(group)
            continue
        same = pair and group.kind == 'angle' and group.label == corner_name(pair) and all(
            any(p.get('element') == m.number and p['label'] == m.label and p.get('width_m') is not None and
                abs(p['width_m']-json.loads(m.snapshot)['width']) < 1e-6 for p in pair) for m in group.members)
        cups = [assignments.get(m.number) for m in group.members]
        has_fiche = any(m.fiche_id for m in group.members)
        if same and has_fiche:
            if not all(cups) or any(c.id != json.loads(m.snapshot)['coupe_id'] for c, m in zip(cups, group.members)):
                problems.append(issue(involved, 'project', f'{group.label}: i bracci con fiche devono restare nella coupe originale.',
                                      f'{group.label} : les branches avec fiche doivent rester dans la coupe d’origine.', 409))
            retained.append(group)
        elif not same and (has_fiche or group.kind != 'angle'):
            problems.append(issue(involved, 'project', f'{group.label}: esistono dati di produzione. Gestisci prima il gruppo dalla pagina cantiere.',
                                  f'{group.label} : des données de production existent. Gérez d’abord le groupe dans la page du chantier.', 409))
            retained.append(group)
        elif same and all(cups) and len({c.id for c in cups}) == 1 and all(c.profondita_teorica and c.spessore for c in cups):
            retained.append(group)
    fiches = {f.numero_pannello for f in db.query(Fiche).filter_by(site_id=site.id, tipologia_scavo='paratia')}
    for ids, pair in new_pairs.items():
        label = corner_name(pair) or ' / '.join(p['label'] for p in pair)
        cups = [assignments.get(n) for n in ids]
        if all(cups) and len({c.id for c in cups}) != 1:
            problems.append(issue(pair, 'project', f'{label}: assegna i due bracci alla stessa coupe per la fiche unica.',
                                  f'{label} : affectez les deux branches à la même coupe pour la fiche unique.'))
        elif all(cups) and all(c.profondita_teorica and c.spessore for c in cups):
            if any(frozenset(m.number for m in g.members) == ids and g.kind == 'angle' for g in retained):
                continue
            if any(m.number in ids for g in retained for m in g.members) or ids & fiches:
                problems.append(issue(pair, 'project', f'{label}: un braccio ha già una fiche o appartiene a un altro getto. Gestisci prima il gruppo nel cantiere.',
                                      f'{label} : une branche possède déjà une fiche ou appartient à un autre bétonnage. Gérez d’abord le groupe dans le chantier.', 409))
            if any(not math.isfinite(float(v)) or v <= 0 for c in cups for v in (c.profondita_teorica, c.spessore)):
                problems.append(issue(pair, 'project', f'{label}: controlla profondità e spessore della coupe.',
                                      f'{label} : vérifiez la profondeur et l’épaisseur de la coupe.'))
    return problems
