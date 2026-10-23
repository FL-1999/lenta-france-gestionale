"""Progress counts physical panels; approved A/B corners are one unit.

Stable element numbers remain unchanged for plans, coupes, cages and fiches.
Joint pours do not merge their distinct panels for progress purposes.
"""
import math

from sqlalchemy import inspect
from sqlalchemy.orm import object_session

from services.site_pours import completed_numbers


def count_panels(total, fiches, corners=()):
    total = max(0, int(total or 0))
    numbers = set(range(1, total + 1))
    units, grouped = [], set()
    for pair in corners:
        pair = frozenset(pair)
        # Only complete, non-overlapping configured pairs can become one panel.
        if len(pair) == 2 and pair <= numbers and not pair & grouped:
            units.append(pair)
            grouped.update(pair)
    units.extend(frozenset([n]) for n in sorted(numbers - grouped))
    done_numbers = completed_numbers(fiches, total)
    recorded = set()
    for fiche in fiches:
        if fiche.tipologia_scavo != 'paratia':
            continue
        recorded.add(fiche.numero_pannello)
        recorded.update(m.number for m in getattr(fiche, 'pour_panels', []))
    done = sum(unit <= done_numbers for unit in units)
    pending = sum(bool(unit & recorded) and not unit <= done_numbers for unit in units)
    return dict(done=done, total=len(units), percent=round(done / len(units) * 100) if units else 0,
                pending=pending, remaining=len(units)-done, angles=len(grouped)//2)


def _configured_total(site):
    return next((getattr(site, key, None) for key in
                  ('numero_totale_paratie', 'totale_paratie_da_scavare', 'paratie_total_panels')
                  if getattr(site, key, None) is not None), 0)


def planned_surface(site, db=None):
    """Vertical project area, counting each stable element/angle branch once.

    Use approved net plan widths and assigned coupe depths. Without a plan
    width, an explicitly assigned coupe width is also a project measurement.
    Fiche measurements and pour snapshots must never change the target.
    """
    from models import SiteCoupeAssignment
    from sqlalchemy.orm import joinedload
    from services.site_plan_project import approved_panels

    if db is None and inspect(site, raiseerr=False) is not None:
        db = object_session(site)
    expected = set(range(1, max(0, int(_configured_total(site) or 0)) + 1))
    panels, coupes = {}, {}
    if db is not None:
        panels = {p['element']: p for p in approved_panels(db, site.id) if p.get('element')}
        coupes = {a.numero_elemento: a.coupe for a in db.query(SiteCoupeAssignment)
                  .options(joinedload(SiteCoupeAssignment.coupe))
                  .filter_by(site_id=site.id, tipologia_scavo='paratia')}
    expected.update(panels)
    expected.update(coupes)

    def positive(value):
        try:
            value = float(value)
            return value if math.isfinite(value) and value > 0 else None
        except (TypeError, ValueError):
            return None

    areas, missing = [], 0
    for number in expected:
        coupe = coupes.get(number)
        width = panels.get(number, {}).get('width_m')
        if width is None:
            width = getattr(coupe, 'larghezza', None)
        width = positive(width)
        depth = positive(getattr(coupe, 'profondita_teorica', None))
        if width is None or depth is None:
            missing += 1
        else:
            areas.append(width * depth)
    # A partial area is not the site total and must not drive a percentage.
    return dict(total=round(math.fsum(areas), 2) if expected and not missing else None,
                missing=missing, elements=len(expected))


def panel_progress(site, fiches=None, db=None):
    total = _configured_total(site)
    if db is None and inspect(site, raiseerr=False) is not None:
        db = object_session(site)
    if fiches is None:
        fiches = list(site.fiches) if db is not None else []
    corners = []
    if db is not None:
        from models import SitePour
        from services.site_plan_project import approved_panels
        from services.plan_corners import groups, corner_name
        # Include corners already approved on the plan, before coupe/fiche setup.
        for pair in groups(approved_panels(db, site.id)).values():
            if corner_name(pair):
                corners.append([p.get('element') for p in pair])
        corners.extend([m.number for m in group.members] for group in
                       db.query(SitePour).filter_by(site_id=site.id, kind='angle'))
    else:
        for fiche in fiches:
            for member in getattr(fiche, 'pour_panels', []):
                if member.pour.kind == 'angle':
                    corners.append([m.number for m in member.pour.members])
    return count_panels(total, fiches, corners)
