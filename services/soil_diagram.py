"""Shared elevation scale for the encountered and theoretical soil columns."""
from html import escape

COLORS = {
    "soil-layer--riporto": "#c8cdd4", "soil-layer--ghiaia": "#d8c0a0",
    "soil-layer--argilla": "#a8c4a0", "soil-layer--sabbia": "#e8d890",
    "soil-layer--roccia": "#a0a8b0", "soil-layer--limo": "#c8b898",
}


def comparison_svg(encountered, theoretical, origin, datum="NGF", depth=None):
    rows = [encountered or [], theoretical or []]
    extent = max([float(depth or 0), 1] + [float(layer["a"]) for group in rows for layer in group])
    top, bottom = 54, 636
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 220 666" '
        'class="soil-comparison-svg" role="img" aria-label="Comparaison des sols et cotes">',
        '<rect width="220" height="666" fill="white"/>',
        f'<text x="110" y="17" text-anchor="middle" font-family="Arial" font-size="13" '
        f'font-weight="bold">Cotes {escape(str(datum))} (m)</text>',
    ]
    for column, layers in enumerate(rows):
        x, width = 6 + column * 110, 98
        parts.append(f'<text x="{x+width/2}" y="40" text-anchor="middle" font-family="Arial" '
                     f'font-size="13" font-weight="bold">{"Rencontré" if column == 0 else "Théorique"}</text>')
        parts.append(f'<rect x="{x}" y="{top}" width="{width}" height="{bottom-top}" fill="#f8fafc" stroke="#475569"/>')
        levels = set()
        for layer in layers:
            start, end = float(layer["da"]), float(layer["a"])
            y = top + start / extent * (bottom-top)
            height = (end-start) / extent * (bottom-top)
            color = COLORS.get(layer.get("texture_class"), "#e2e8f0")
            parts.append(f'<rect x="{x}" y="{y:.2f}" width="{width}" height="{height:.2f}" '
                         f'fill="{color}" fill-opacity="{1 if column == 0 else .65}" stroke="#64748b" stroke-width=".6"/>')
            levels.update((start, end))
        if not layers:
            parts.append(f'<text x="{x+width/2}" y="{top+30}" text-anchor="middle" font-family="Arial" font-size="13">Non renseigné</text>')
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
            parts.append(f'<path d="M{x},{y:.2f} h8 L{x+17},{label_y:.2f}" stroke="#334155" fill="none"/>')
            parts.append(f'<rect x="{x+17}" y="{label_y-8:.2f}" width="72" height="16" rx="2" fill="white" fill-opacity=".94"/>')
            parts.append(f'<text x="{x+53}" y="{label_y+4.5:.2f}" text-anchor="middle" font-family="Arial" '
                         f'font-size="14" font-weight="bold">{label}</text>')
    parts.append('<text x="110" y="658" text-anchor="middle" font-family="Arial" font-size="11">Même échelle de profondeur</text></svg>')
    return "".join(parts)
