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
    levels=[Level(id=f'level-{l.level_index}', name=f'Livello -{l.level_index}') for l in site.strut_levels]
    if not levels:
        alternatives={tuple(sorted(set(c.drawing_info.get('struts',[])),reverse=True))
                      for c in site.coupes if c.drawing_info and c.drawing_info.get('reviewed')}
        # Different coupes can describe the same storey at different elevations.
        # Only prefill an unambiguous set; never invent extra site-wide levels.
        axes=next(iter(alternatives)) if len(alternatives)==1 else ()
        levels=[Level(id=f'level-{i+1}',name=f'Livello -{i+1}',axis_ngf=axis) for i,axis in enumerate(axes)]
    return Works(levels=levels).model_dump(mode='json')


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
            if s['panel_a'] not in panels or s['panel_b'] not in panels or s['panel_a'] == s['panel_b']:
                raise ValueError('Scegli due pannelli di appoggio distinti della pianta.')
            position(s['a']); position(s['b'])
            if math.dist(s['a'], s['b']) < 1:
                raise ValueError('Gli appoggi del puntone coincidono.')
            mid = [(a+b)/2 for a,b in zip(s['a'], s['b'])]
            s['a'] = support_face(mid, s['a'], panels[s['panel_a']]['points'])
            s['b'] = support_face(mid, s['b'], panels[s['panel_b']]['points'])
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
    return {'struts': len(struts), 'installed': sum(s['status']=='installed' for s in struts),
            'removed': sum(s['status']=='removed' for s in struts), 'wells': len(value['wells']),
            'wells_done': sum(w['status']!='planned' for w in value['wells']),
            'pumping': sum(w['status']=='pumping' for w in value['wells']), 'rabotage': len(value['rabotage'])}
