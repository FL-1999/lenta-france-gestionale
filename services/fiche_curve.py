"""PDF-only elevation chart: the operational editor retains its depth inputs."""
from html import escape
from math import isfinite, pi
from services.fiche_language import report_translator


def curve_depth_increases(points):
    """Flag suspicious readings without changing or discarding measurements."""
    ordered = sorted(points, key=lambda p: p['volume'])
    return any(b['volume'] > a['volume'] and b['hauteur'] > a['hauteur'] + 1e-6
               for a, b in zip(ordered, ordered[1:]))


def curve_defaults(fiche):
    """Theoretical data only. Never infer measured pouring points or actual volume."""
    def number(name):
        value = getattr(fiche, name, None)
        try:
            return float(value) if value is not None and isfinite(float(value)) else None
        except (TypeError, ValueError):
            return None
    depth = number('profondita_totale')
    if depth is None:
        origin, bottom = number('quota_partenza'), number('quota_ngf_fondo')
        depth = origin - bottom if origin is not None and bottom is not None else None
    depth = depth if depth is not None and depth > 0 else None
    width, thickness, diameter = number('larghezza_pannello'), number('altezza_pannello'), number('diametro_palo')
    kind = (getattr(fiche, 'tipologia_scavo', '') or '').lower()
    section = None
    if kind == 'paratia' and width is not None and thickness is not None and width > 0 and thickness > 0:
        section = width * thickness
    elif kind == 'palo' and diameter is not None and diameter > 0:
        section = pi * (diameter / 2) ** 2
    return {'volume': round(section * depth, 2) if section is not None and depth is not None else None,
            'start': depth, 'end': 0.0}


def curve_values(fiche):
    values = curve_defaults(fiche)
    for key, field in (('volume', 'courbe_beton_volume_total'), ('start', 'courbe_beton_hauteur_initiale')):
        value = getattr(fiche, field, None)
        if value is not None:
            values[key] = value
    return values


def compact_courbe_svg(payload, origin, datum='NGF', *, language='fr'):
    tr = report_translator(language)
    series = [payload.get(k) or [] for k in ('realisee', 'theorique', 'tube')]
    points = [p for s in series for p in s]
    if origin is None or not points:
        return f'<p>{tr("Non renseigné")} ({escape(str(datum))})</p>'
    # hauteur is the measured distance down from the drilling origin.
    max_x = max([1.] + [float(p['volume']) for p in points])
    max_depth = max([1.] + [float(p['hauteur']) for p in points])
    width, height = 180, 238
    left, right, top, bottom = 36, 170, 22, 194
    def sx(v): return left + float(v)/max_x*(right-left)
    def sy(v): return top + float(v)/max_depth*(bottom-top)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" class="b-curve-svg" role="img" aria-label="{tr("COURBE DE BÉTONNAGE")}">',
             f'<text x="{left}" y="12" font-family="Arial" font-size="9">m {escape(str(datum))}</text>']
    for i in range(5):
        x, y = left+(right-left)*i/4, top+(bottom-top)*i/4
        parts += [f'<path d="M{x} {top} V{bottom} M{left} {y} H{right}" fill="none" stroke="#ddd" stroke-width=".7"/>',
                  f'<text x="{left-3}" y="{y+3}" text-anchor="end" font-family="Arial" font-size="9">{float(origin)-max_depth*i/4:.2f}</text>',
                  f'<text x="{x}" y="{bottom+12}" text-anchor="middle" font-family="Arial" font-size="9">{max_x*i/4:.1f}</text>']
    for rows, color in zip(series, ('#2563eb', '#dc2626', '#16a34a')):
        if rows:
            coords = ' '.join(f"{sx(p['volume']):.2f},{sy(p['hauteur']):.2f}" for p in rows)
            parts.append(f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="1.5"/>')
            for p in rows:
                parts.append(f'<circle cx="{sx(p["volume"]):.2f}" cy="{sy(p["hauteur"]):.2f}" r="1.7" fill="white" stroke="{color}"/>')
    parts.append(f'<text x="103" y="220" text-anchor="middle" font-family="Arial" font-size="9">{tr("Volume en m³")}</text>')
    for x, label, color in ((3, 'Réalisée', '#2563eb'), (65, 'Théorique', '#dc2626'), (135, 'Tube', '#16a34a')):
        parts.append(f'<text x="{x}" y="236" font-family="Arial" font-size="9" fill="{color}">{tr(label)}</text>')
    return ''.join(parts)+'</svg>'
