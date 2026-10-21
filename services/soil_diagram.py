"""Shared elevation scale for the encountered and theoretical soil columns."""
from html import escape
import textwrap
from services.fiche_language import report_translator, technical_text

COLORS = {
    "soil-layer--riporto": "#c8cdd4", "soil-layer--ghiaia": "#d8c0a0",
    "soil-layer--argilla": "#a8c4a0", "soil-layer--sabbia": "#e8d890",
    "soil-layer--roccia": "#a0a8b0", "soil-layer--limo": "#c8b898",
}


def comparison_svg(encountered, theoretical, origin, datum="NGF", depth=None,
                   *, aligned=False, language="fr"):
    tr = report_translator(language)
    rows = [encountered or [], theoretical or []]
    extent = max([float(depth or 0), 1] + [float(layer["a"]) for group in rows for layer in group])
    top, bottom = (147, 900) if aligned else (54, 636)
    width, height = (264, 980) if aligned else (220, 666)
    font = 16 if aligned else 13
    column_width = width / 2 - 12
    parts = [
        (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
         + ('x="530" y="0" width="264" height="980" ' if aligned else '')
         + f'class="soil-comparison-svg" role="img" aria-label="{tr("Comparaison des sols et cotes")}">'),
        f'<text x="{width/2}" y="{top-38}" text-anchor="middle" font-family="Arial" font-size="{font}" '
        f'font-weight="bold">{tr("Cotes")} {escape(str(datum))} (m)</text>',
    ]
    for column, layers in enumerate(rows):
        x = 6 + column * width / 2
        parts.append(f'<text x="{x+column_width/2}" y="{top-14}" text-anchor="middle" font-family="Arial" '
                     f'font-size="{font}" font-weight="bold">{tr("Rencontré" if column == 0 else "Théorique")}</text>')
        parts.append(f'<rect class="soil-column-frame" x="{x}" y="{top}" width="{column_width}" height="{bottom-top}" fill="#f8fafc" stroke="#475569"/>')
        levels = set()
        for layer in layers:
            start, end = float(layer["da"]), float(layer["a"])
            y = top + start / extent * (bottom-top)
            layer_height = (end-start) / extent * (bottom-top)
            color = COLORS.get(layer.get("texture_class"), "#e2e8f0")
            parts.append(f'<rect x="{x}" y="{y:.2f}" width="{column_width}" height="{layer_height:.2f}" '
                         f'fill="{color}" fill-opacity="{1 if column == 0 else .65}" stroke="#64748b" stroke-width=".6"/>')
            levels.update((start, end))
        if not layers:
            parts.append(f'<text x="{x+column_width/2}" y="{top+30}" text-anchor="middle" font-family="Arial" font-size="13">{tr("Non renseigné")}</text>')
        # Keep thin-layer labels apart and draw a leader to the exact boundary.
        depths = sorted(levels)
        if len(depths) > 28:
            # Dense logs have every boundary in the A4 annex; keep the diagram legible.
            step = (len(depths) - 1) / 27
            depths = [depths[round(i * step)] for i in range(28)]
        actual = [top + value/extent*(bottom-top) for value in depths]
        positions = []
        for y in actual:
            positions.append(max(y, positions[-1]+18 if positions else top))
        if positions:
            positions[-1] = min(positions[-1], bottom)
            for i in range(len(positions)-2, -1, -1):
                positions[i] = min(positions[i], positions[i+1]-18)
        for value, y, label_y in zip(depths, actual, positions):
            label = f"{float(origin)-value:.2f}".replace(".", ",") if origin is not None else "—"
            center = x + column_width/2
            parts.append(f'<path d="M{x},{y:.2f} h8 L{center-36},{label_y:.2f}" stroke="#334155" fill="none"/>')
            parts.append(f'<rect x="{center-36}" y="{label_y-8:.2f}" width="72" height="16" rx="2" fill="white" fill-opacity=".94"/>')
            parts.append(f'<text x="{center}" y="{label_y+4.5:.2f}" text-anchor="middle" font-family="Arial" '
                         f'font-size="{font+1}" font-weight="bold">{label}</text>')
    parts.append(f'<text x="{width/2}" y="{bottom+24}" text-anchor="middle" font-family="Arial" font-size="12">{tr("Même échelle de profondeur")}</text></svg>')
    return "".join(parts)


def panel_report_svg(encountered, theoretical, origin, datum, depth, tn,
                     width_label, thickness_label, mechanical_base, hydraulic_base, *, language="fr", compact=False, concrete_top=None):
    """One vector coordinate system for the wall, guide walls and soil levels.

    The front excavation face and both log frames share y=147..900. Keeping
    them in one SVG avoids independent CSS transforms and opaque overlapping
    boxes in Chromium, browser printing and the WeasyPrint fallback.
    """
    tr = report_translator(language)

    def number(value):
        return f"{float(value):.2f}".replace(".", ",") if value is not None else "—"

    ref = escape(str(datum))
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 980" '
        'width="800" height="980" class="technical-panel-diagram" role="img" '
        f'aria-label="{tr("Paroi, murettes guides et sols à la même échelle")}">',
        '<g font-family="Arial" fill="#111">',
    ]
    if compact:
        # Align the elevation key with the outer edges of the guide walls.
        # Labels and values share columns instead of floating over the drawing.
        elevations = [("Terrain naturel (TN)", tn), ("Départ du forage", origin)]
        if concrete_top is not None:
            elevations.append(("Cote tête béton", concrete_top))
        key_height = len(elevations) * 17 + 4
        parts.append(f'<g class="panel-elevation-key" font-size="13">'
                     f'<rect x="115" y="30" width="370" height="{key_height}" fill="#f1f5f8"/>')
        for index, (label, value) in enumerate(elevations):
            y = 43 + index * 17
            parts.append(f'<text class="panel-top-label" x="125" y="{y}" fill="#334155">{tr(label)}</text>'
                         f'<text class="panel-top-value" x="475" y="{y}" text-anchor="end" font-weight="bold">{number(value)} {ref}</text>')
        parts.append('</g>')
    else:
        parts.extend([
            f'<text class="panel-top-label" x="400" y="25" text-anchor="middle" font-size="18" font-weight="bold">{tr("Terrain naturel (TN)")} : {number(tn)} {ref}</text>',
            f'<text class="panel-top-label" x="400" y="53" text-anchor="middle" font-size="18" font-weight="bold">{tr("Départ du forage (profondeur 0 m)")} : {number(origin)} {ref}</text>',
        ])
    parts.extend([
        # The complete geometry moves down 40 units; no face is cropped.
        '<g transform="translate(0 40)">',
        '<g class="panel-guide-back" stroke="#555" stroke-width="1.5">',
        '<polygon points="165,77 465,77 485,57 185,57" fill="#a6a6a6"/>',
        '<polygon points="465,77 485,57 485,97 465,117" fill="#8e8e8e"/>',
        '</g>',
        '<polygon points="435,107 465,77 465,830 435,860" fill="#d8af73" fill-opacity=".7" stroke="#c07820" stroke-width="1.5"/>',
        '<polygon points="135,107 435,107 465,77 165,77" fill="#e8d6b0" stroke="#c07820" stroke-width="1.5"/>',
        '<rect class="panel-front-face" x="135" y="107" width="300" height="753" fill="#fff8dc" stroke="#c07820" stroke-width="1.5"/>',
        '<g class="panel-guide-front" stroke="#555" stroke-width="1.5">',
        '<polygon points="135,107 435,107 415,127 115,127" fill="#a6a6a6"/>',
        '<polygon points="415,127 435,107 435,147 415,167" fill="#8e8e8e"/>',
        '<polygon points="115,127 415,127 415,167 115,167" fill="#c8c8c8"/>',
        '</g>',
        f'<text x="265" y="152" text-anchor="middle" font-size="13" font-weight="bold">{tr("Murette Guide")}</text>',
        '<g stroke="#c00" stroke-width="2.5" fill="none">',
        '<path d="M140 530 H430 M105 107 V860 M435 665 L465 635"/>',
        '</g>',
        '<g fill="#c00">',
        '<polygon points="135,530 148,524 148,536"/><polygon points="435,530 422,524 422,536"/>',
        '<polygon points="105,100 99,113 111,113"/><polygon points="105,867 99,854 111,854"/>',
        '<polygon points="435,665 446,661 439,654"/><polygon points="465,635 461,646 454,639"/>',
        f'<text x="90" y="484" text-anchor="middle" transform="rotate(-90 90 484)" font-size="16" font-weight="bold">{tr("Longueur forée")} = {number(depth)} m</text>',
        f'<text x="285" y="518" text-anchor="middle" font-size="16" font-weight="bold">{tr("Largeur")} = {escape(str(width_label))}</text>',
        f'<text x="285" y="678" text-anchor="middle" font-size="15" font-weight="bold">{tr("Epaisseur")} = {escape(str(thickness_label))}</text>',
        '</g></g>',
    ])
    for y, label, value in ((940, "BASE PAROI MECANIQUE", mechanical_base),
                             (963, "BASE PAROI HYDRAULIQUE", hydraulic_base)):
        if value is not None:
            parts.append(f'<text x="285" y="{y}" text-anchor="middle" font-size="14" font-weight="bold">{tr(label)} = {number(value)} {ref}</text>')
    parts.append('</g>')
    parts.append(comparison_svg(encountered, theoretical, origin, datum, depth, aligned=True, language=language))
    parts.append('</svg>')
    svg = "".join(parts)
    if compact:
        # Crop empty canvas only. The wall/guide geometry and uniform scale stay identical.
        svg = svg.replace('viewBox="0 0 800 980"', 'viewBox="75 0 606 980"').replace('width="800"', 'width="606"')
        svg = svg.replace(f'{tr("Longueur forée")} = {number(depth)} m',
                          f'{number(origin)} → {number(hydraulic_base)} m {ref}')
        old = comparison_svg(encountered, theoretical, origin, datum, depth, aligned=True, language=language)
        svg = svg.replace(old, narrow_soils_svg(encountered, theoretical, origin, datum, depth, language=language))
    return svg


def soil_label_lines(layer, language):
    return textwrap.wrap(technical_text(layer.get('materiale', ''), language), width=11,
                         break_long_words=True, break_on_hyphens=False) or ['—']


def soils_need_annex(encountered, theoretical, depth, language='fr'):
    extent = float(depth or 1)
    for rows in (encountered or [], theoretical or []):
        if len(rows) > 6:
            return True
        for layer in rows:
            start, end = float(layer['da']), float(layer['a'])
            if start < 0 or end > extent or (end-start)/extent*753 < len(soil_label_lines(layer, language))*16+24:
                return True
    return False


def narrow_soils_svg(encountered, theoretical, origin, datum, depth, *, language='fr'):
    """17 mm logs at the wall's exact scale; no opaque container can cover a guide wall."""
    tr = report_translator(language)
    extent = float(depth or 1)
    top, height, width = 147, 753, 74
    parts = ['<g class="soil-comparison-narrow" font-family="Arial" fill="#111">']
    for col, rows in enumerate((encountered or [], theoretical or [])):
        x = 518 + col*87
        center = x+width/2
        parts += [f'<text x="{center}" y="115" text-anchor="middle" font-size="11.8" font-weight="bold">{tr("Rencontré" if col == 0 else "Théorique")}</text>',
                  f'<text x="{center}" y="131" text-anchor="middle" font-size="11">m {escape(str(datum))}</text>',
                  f'<rect class="soil-column-frame" x="{x}" y="147" width="{width}" height="753" fill="#fafafa" stroke="#64748b"/>']
        levels = set()
        for index, layer in enumerate(rows):
            start, end = max(0, float(layer['da'])), min(extent, float(layer['a']))
            if start >= end:
                continue
            y, h = top+start/extent*height, (end-start)/extent*height
            color = COLORS.get(layer.get('texture_class'), '#e2e8f0')
            parts.append(f'<rect x="{x}" y="{y:.2f}" width="{width}" height="{h:.2f}" fill="{color}" fill-opacity="{1 if col == 0 else .65}" stroke="#64748b" stroke-width=".6"/>')
            lines = soil_label_lines(layer, language)
            if h < len(lines)*16+24:
                lines = [f'[{index+1}]'] if h >= 32 else []
            for n, line in enumerate(lines):
                ly = y+h/2+(n-(len(lines)-1)/2)*16+4
                parts.append(f'<text class="soil-material-label" x="{center}" y="{ly:.2f}" text-anchor="middle" font-size="11.8">{escape(line)} </text>')
            levels.update((start, end))
        if not rows:
            for n, line in enumerate(textwrap.wrap(tr('Non renseigné'), 11)):
                parts.append(f'<text x="{center}" y="{200+n*16}" text-anchor="middle" font-size="11.8">{escape(line)} </text>')
        # Every omitted boundary is retained in the automatically generated annex.
        last_y = -100
        for value in sorted(levels):
            y = top+value/extent*height
            if value != extent and top+height-y < 18:
                continue
            if y-last_y < 18 and value != extent:
                continue
            last_y = y
            label = f'{float(origin)-value:.2f}'.replace('.', ',') if origin is not None else '—'
            parts.append(f'<rect x="{x+6}" y="{y-7:.2f}" width="{width-12}" height="14" fill="#fff" fill-opacity=".94"/>')
            parts.append(f'<text class="soil-ngf-label" x="{center}" y="{y+4:.2f}" text-anchor="middle" font-size="11.8" font-weight="bold">{label}</text>')
    return ''.join(parts)+'</g>'
