"""Reviewed work-map data, geometric supports and independent progress totals."""
import json
import math
from datetime import date
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

Key = Annotated[str, Field(pattern=r'^[a-zA-Z0-9_-]{1,80}$')]
Name = Annotated[str, Field(min_length=1, max_length=80)]
Point = tuple[FiniteFloat, FiniteFloat]
Measure = Annotated[FiniteFloat, Field(gt=0, le=100000)]
Angle = Annotated[FiniteFloat, Field(ge=0, le=180)]


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class Strut(Strict):
    id: Key
    label: Name
    panel_a: Key
    panel_b: Key
    a: Point
    b: Point
    length_m: Measure | None = None
    diameter_mm: Measure | None = None
    thickness_mm: Measure | None = None
    angle_a: Angle | None = None
    angle_b: Angle | None = None
    fixation_a: str = Field('', max_length=100)
    fixation_b: str = Field('', max_length=100)
    verine: str = Field('', max_length=150)
    status: Literal['planned', 'installed', 'removed'] = 'planned'
    installed_on: date | None = None
    removed_on: date | None = None
    notes: str = Field('', max_length=2000)
    source_id: int | None = Field(None, gt=0)

    @model_validator(mode='after')
    def dates(self):
        if self.installed_on and self.removed_on and self.removed_on < self.installed_on:
            raise ValueError('La rimozione precede la posa.')
        if self.thickness_mm and self.diameter_mm and self.thickness_mm * 2 >= self.diameter_mm:
            raise ValueError('Controlla diametro e spessore del tubo.')
        return self


class Level(Strict):
    id: Key
    name: Name
    axis_ngf: Annotated[FiniteFloat, Field(ge=-10000, le=10000)] | None = None
    struts: list[Strut] = Field(default_factory=list, max_length=300)
    planned_count: int = Field(default=0, ge=0, le=10000)
    completed_count: int = Field(default=0, ge=0, le=10000)

    @model_validator(mode='after')
    def quantities(self):
        if self.completed_count > self.planned_count:
            raise ValueError('I puntoni eseguiti non possono superare quelli previsti.')
        return self


class Well(Strict):
    id: Key
    label: Name
    point: Point
    status: Literal['planned', 'completed', 'pumping', 'stopped'] = 'planned'
    notes: str = Field('', max_length=2000)


class Works(Strict):
    levels: list[Level] = Field(default_factory=list, max_length=30)
    wells: list[Well] = Field(default_factory=list, max_length=300)
    rabotage: list[Annotated[int, Field(gt=0)]] = Field(default_factory=list, max_length=500)


def empty_works(site):
    # Legacy aggregates remain visible, but never invent individual placed struts.
    levels=[Level(id=f'level-{l.level_index}', name=f'Livello -{l.level_index}',
                  planned_count=max(l.total_struts_level or 0, l.done_struts_level or 0),
                  completed_count=l.done_struts_level or 0) for l in site.strut_levels]
    alternatives={tuple(sorted(set(c.drawing_info.get('struts',[])),reverse=True))
                  for c in site.coupes if c.drawing_info and c.drawing_info.get('reviewed')}
    axes=next(iter(alternatives)) if len(alternatives)==1 else ()
    if not levels:
        # Different coupes can describe the same storey at different elevations.
        # Only prefill an unambiguous set; never invent extra site-wide levels.
        levels=[Level(id=f'level-{i+1}',name=f'Livello -{i+1}',axis_ngf=axis) for i,axis in enumerate(axes)]
    elif len(levels)==len(axes):
        for level,axis in zip(levels,axes):
            level.axis_ngf=axis
    return Works(levels=levels).model_dump(mode='json')


def resolved_works(site):
    """Expose existing configuration without inventing strut positions or duplicating levels."""
    configured=empty_works(site)
    if not site.works_map:
        return configured
    value=json.loads(site.works_map.payload)
    if not value['levels']:
        value['levels']=configured['levels']
    defaults={level['id']:level for level in configured['levels']}
    for level in value['levels']:
        previous=defaults.get(level['id'])
        if previous:
            for key in ('planned_count','completed_count'):
                level.setdefault(key,previous[key])
            if level.get('axis_ngf') is None and not level['struts']:
                level['axis_ngf']=previous['axis_ngf']
    return Works.model_validate(value).model_dump(mode='json')


def guide_configuration(site):
    from sqlalchemy.orm import object_session
    from models import SitePlan
    from services.plan_selection import current_plan
    db=object_session(site)
    plan=current_plan(db.query(SitePlan).filter_by(site_id=site.id).all()) if db else None
    panels=json.loads(plan.approved)['panels'] if plan and plan.approved else []
    widths=[p.get('width_m') for p in panels]
    # Net widths already include each arm once. Never use an image perimeter or a partial sum.
    length=round(sum(widths),3) if widths and all(w is not None and w>0 for w in widths) else None
    automatic=not site.cordoli_total_m or site.cordoli_total_m<=0
    return dict(wall_length_m=length,guide_auto=automatic,
                guide_total_m=(length or 0) if automatic else site.cordoli_total_m,
                guide_done_m=site.cordoli_done_m or 0)


def level_counts(level):
    if level['struts']:
        return len(level['struts']),sum(s['status']!='planned' for s in level['struts'])
    return level.get('planned_count',0),level.get('completed_count',0)


def cross(a, b):
    return a[0]*b[1]-a[1]*b[0]


def sub(a, b):
    return (a[0]-b[0], a[1]-b[1])


def support_face(mid, toward, polygon):
    """First face reached from between the supports (not the wall centre/outer face)."""
    ray = sub(toward, mid)
    hits = []
    for a, b in zip(polygon, polygon[1:]+polygon[:1]):
        edge = sub(b, a)
        denominator = cross(ray, edge)
        if abs(denominator) < 1e-9:
            continue
        t = cross(sub(a, mid), edge)/denominator
        u = cross(sub(a, mid), ray)/denominator
        if t > 0 and -.000001 <= u <= 1.000001:
            hits.append((t, [mid[0]+t*ray[0], mid[1]+t*ray[1]]))
    if not hits:
        raise ValueError('L’asse non incontra il pannello di appoggio. Riposiziona l’estremità sulla mappa.')
    return min(hits, key=lambda h: h[0])[1]


def support_members(key, panels):
    """Keep the approved A/B corner as one support, with both original identities."""
    panel = panels[key]
    group = panel.get('corner_group')
    members = [p for p in panels.values() if p.get('corner_group') == group] if group else [panel]
    return members if len(members) == 2 else [panel]


def corner_support_face(mid, toward, members):
    hits = []
    for panel in members:
        try:
            hits.append(support_face(mid, toward, panel['points']))
        except ValueError:
            continue
    if not hits:
        raise ValueError('L’asse non incontra il pannello di appoggio. Riposiziona l’estremità sulla mappa.')
    return min(hits, key=lambda p: math.dist(mid, p))


def validate_works(data, layout):
    value = Works.model_validate(data).model_dump(mode='json')
    panels = {p['key']: p for p in layout['panels']}
    elements = {p.get('element') for p in panels.values()} - {None}
    ids = set()
    def identity(key):
        if key in ids:
            raise ValueError('Identificativo ripetuto nella mappa.')
        ids.add(key)
    def position(p):
        if not 0 <= p[0] <= layout['width'] or not 0 <= p[1] <= layout['height']:
            raise ValueError('Posizione fuori dalla pianta.')
    for level in value['levels']:
        identity(level['id'])
        labels = set()
        for s in level['struts']:
            identity(s['id'])
            if s['label'].casefold() in labels:
                raise ValueError('Sigla puntone ripetuta nello stesso livello.')
            labels.add(s['label'].casefold())
            if s['panel_a'] not in panels or s['panel_b'] not in panels:
                raise ValueError('Scegli due pannelli di appoggio distinti della pianta.')
            supports = {end: support_members(s['panel_'+end], panels) for end in ('a', 'b')}
            if s['panel_a'] == s['panel_b'] and len(supports['a']) == 1:
                raise ValueError('Scegli due pannelli di appoggio distinti della pianta.')
            position(s['a']); position(s['b'])
            if math.dist(s['a'], s['b']) < 1:
                raise ValueError('Gli appoggi del puntone coincidono.')
            mid = [(a+b)/2 for a,b in zip(s['a'], s['b'])]
            s['a'] = corner_support_face(mid, s['a'], supports['a'])
            s['b'] = corner_support_face(mid, s['b'], supports['b'])
            position(s['a']); position(s['b'])
            # A straight strut cannot pass through a third wall panel.
            for key,p in panels.items():
                if key in (s['panel_a'], s['panel_b']):
                    continue
                ray = sub(s['b'], s['a'])
                for a,b in zip(p['points'], p['points'][1:]+p['points'][:1]):
                    edge = sub(b,a); den = cross(ray,edge)
                    if abs(den)<1e-9:
                        continue
                    t,u = cross(sub(a,s['a']),edge)/den, cross(sub(a,s['a']),ray)/den
                    if .002<t<.998 and .002<u<.998:
                        raise ValueError(f"{s['label']}: l’asse attraversa il pannello {p['label']}. Controlla gli appoggi.")
    for w in value['wells']:
        identity(w['id']); position(w['point'])
    if len(value['rabotage']) != len(set(value['rabotage'])) or not set(value['rabotage']) <= elements:
        raise ValueError('Rabotage: scegli pannelli presenti nella pianta.')
    return value


def object_ids(value):
    return {x['id'] for x in value['wells']+value['levels']} | {
        s['id'] for l in value['levels'] for s in l['struts']}


def merge_import(value, level_id, rows, source_id):
    """Revisions update geometry/specification only; never erase progress or omitted struts."""
    value = json.loads(json.dumps(value))
    level = next((l for l in value['levels'] if l['id']==level_id), None)
    if not level:
        raise ValueError('Seleziona o crea prima il livello dei puntoni.')
    old = {s['label'].casefold(): s for s in level['struts']}
    seen = set()
    for row in rows:
        s = Strut.model_validate(row).model_dump(mode='json')
        key = s['label'].casefold()
        if key in seen:
            raise ValueError('Sigla ripetuta nella selezione da importare.')
        seen.add(key)
        s['source_id'] = source_id
        if key in old:
            existing = old[key]
            for field in ('id','status','installed_on','removed_on','notes'):
                s[field] = existing.get(field)
            level['struts'][level['struts'].index(existing)] = s
        else:
            s.update(id=uuid4().hex, status='planned', installed_on=None, removed_on=None)
            level['struts'].append(s)
    return value


def counts(value):
    struts = [s for l in value['levels'] for s in l['struts']]
    totals=[level_counts(l) for l in value['levels']]
    return {'struts': sum(t for t,d in totals), 'mapped_struts':len(struts), 'installed': sum(s['status']=='installed' for s in struts),
            'placed': sum(d for t,d in totals),
            'removed': sum(s['status']=='removed' for s in struts), 'wells': len(value['wells']),
            'wells_done': sum(w['status']!='planned' for w in value['wells']),
            'pumping': sum(w['status']=='pumping' for w in value['wells']), 'rabotage': len(value['rabotage'])}
