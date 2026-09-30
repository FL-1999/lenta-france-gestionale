"""Keep geological elevations fixed when a fiche uses a different excavation start."""
import re


def rebase_soil(text, old_origin, new_origin):
    if not text or old_origin is None or new_origin is None or abs(old_origin-new_origin) < 1e-8:
        return text
    output = []
    for line in text.splitlines():
        match = re.fullmatch(r'\s*([\d.,]+)\s*[-–]\s*([\d.,]+)\s*m?\s*:\s*(.*)', line)
        if not match:
            output.append(line)
            continue
        start, end = (float(v.replace(',', '.')) + new_origin-old_origin for v in match.groups()[:2])
        if end > 0:
            output.append(f'{max(0, start):g}-{end:g} m: {match[3]}')
    return '\n'.join(output)
