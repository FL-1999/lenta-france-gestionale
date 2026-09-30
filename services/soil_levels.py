"""Keep geological elevations fixed when a fiche uses a different excavation start."""
import re


def theoretical_origin(coupe):
    """The geology reference is independent of the actual excavation start."""
    if getattr(coupe, 'terreno_riferimento', None) == 'tn' or coupe.scavo_da_tn:
        return coupe.quota_tn
    return coupe.quota_partenza_scavo if coupe.quota_partenza_scavo is not None else coupe.quota_testa


def fiche_theory_source(fiche):
    """Reuse the full frozen log when moving the start; preserve manual fiche edits."""
    coupe = fiche.report_coupe if fiche.coupe_snapshot else None
    if coupe:
        source_origin = theoretical_origin(coupe)
        projected = rebase_soil(coupe.terreno_teorico, source_origin, fiche.quota_partenza)
        if projected == fiche.terreno_teorico or fiche.terreno_teorico is None:
            return coupe.terreno_teorico, source_origin
    return fiche.terreno_teorico, fiche.quota_partenza


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
