"""
Production statistics — Sprint 1.
Computed on-the-fly from existing Fiche data. Zero manual re-entry.
Zero economic data. Single Data Entry principle.
"""
from __future__ import annotations

import math
from typing import Optional, Any


# ── Display helper ────────────────────────────────────────────────────────────

def fmt(value: Optional[float], decimals: int = 2, unit: str = "") -> str:
    """Format a numeric value for display. Returns '—' when data is absent."""
    if value is None:
        return "—"
    formatted = f"{value:,.{decimals}f}".replace(",", " ").replace(".", ",")
    return f"{formatted} {unit}" if unit else formatted


# ── Per-fiche volumes ─────────────────────────────────────────────────────────

def compute_fiche_volumes(fiche) -> dict[str, Any]:
    """
    Compute technical volumes for a single production fiche.
    Returns None for any value that cannot be calculated from available data.
    Never returns 0 when the data is simply absent.
    """
    result: dict[str, Any] = {
        "profondita":           None,
        "volume_scavo_teorico": None,
        "volume_cls_teorico":   None,
        "volume_cls_reale":     None,
        "delta_cls":            None,
        "delta_cls_pct":        None,
        "superficie":           None,
        "ml":                   None,
        "tipologia":            (fiche.tipologia_scavo or "—"),
    }

    profondita: Optional[float] = fiche.profondita_totale
    result["profondita"] = profondita

    tipo = (fiche.tipologia_scavo or "").lower()
    is_paratia = tipo in ("paratia", "paroi", "parois", "panneau")
    is_palo    = tipo in ("palo", "pieu", "pieux")

    # ── Paratia ──────────────────────────────────────────────────────────────
    if is_paratia and profondita:
        larghezza: Optional[float] = fiche.larghezza_pannello

        # Spessore from linked coupe (project data, never invented)
        spessore: Optional[float] = None
        if fiche.coupe_id and getattr(fiche, "coupe", None) and fiche.coupe.spessore:
            spessore = fiche.coupe.spessore

        if larghezza and spessore:
            vol = larghezza * spessore * profondita
            result["volume_scavo_teorico"] = round(vol, 3)
            result["volume_cls_teorico"]   = round(vol, 3)

        if larghezza:
            result["superficie"] = round(larghezza * profondita, 2)

    # ── Palo ─────────────────────────────────────────────────────────────────
    elif is_palo and profondita:
        diametro: Optional[float] = fiche.diametro_palo
        if diametro:
            vol = math.pi * (diametro / 2) ** 2 * profondita
            result["volume_scavo_teorico"] = round(vol, 3)
            result["volume_cls_teorico"]   = round(vol, 3)
        result["ml"] = profondita

    # ── Volume cls reale ──────────────────────────────────────────────────────
    # Priority: courbe_beton_volume_total (more precise) > metri_cubi_gettati
    cls_reale: Optional[float] = None
    if fiche.courbe_beton_volume_total:
        cls_reale = fiche.courbe_beton_volume_total
    elif fiche.metri_cubi_gettati:
        cls_reale = fiche.metri_cubi_gettati
    result["volume_cls_reale"] = cls_reale

    # ── Delta teorico/reale ───────────────────────────────────────────────────
    if result["volume_cls_teorico"] is not None and cls_reale is not None:
        delta = round(cls_reale - result["volume_cls_teorico"], 3)
        result["delta_cls"] = delta
        teorico = result["volume_cls_teorico"]
        if teorico and teorico != 0:
            result["delta_cls_pct"] = round(delta / teorico * 100, 1)

    return result


# ── Site-level aggregation ────────────────────────────────────────────────────

def _aggregate_group(fiche_list: list) -> dict[str, Any]:
    """Aggregate volume stats for a group of fiches of the same type."""
    count = len(fiche_list)
    if count == 0:
        return {
            "count": 0,
            "profondita_totale":    None,
            "profondita_media":     None,
            "volume_scavo_teorico": None,
            "volume_cls_teorico":   None,
            "volume_cls_reale":     None,
            "delta_cls":            None,
            "delta_cls_pct":        None,
            "superficie":           None,
            "ml":                   None,
            "cls_reale_coverage":   0,
        }

    pools: dict[str, list[float]] = {
        "profondita":           [],
        "volume_scavo_teorico": [],
        "volume_cls_teorico":   [],
        "volume_cls_reale":     [],
        "delta_cls":            [],
        "superficie":           [],
        "ml":                   [],
    }

    for f in fiche_list:
        v = compute_fiche_volumes(f)
        for key in pools:
            val = v.get(key)
            if val is not None:
                pools[key].append(val)

    def _sum(lst: list[float]) -> Optional[float]:
        return round(sum(lst), 2) if lst else None

    def _avg(lst: list[float]) -> Optional[float]:
        return round(sum(lst) / len(lst), 2) if lst else None

    vol_teorico = _sum(pools["volume_cls_teorico"])
    vol_reale   = _sum(pools["volume_cls_reale"])
    delta       = None
    delta_pct   = None
    if vol_teorico is not None and vol_reale is not None:
        delta = round(vol_reale - vol_teorico, 2)
        if vol_teorico != 0:
            delta_pct = round(delta / vol_teorico * 100, 1)

    return {
        "count":                count,
        "profondita_totale":    _sum(pools["profondita"]),
        "profondita_media":     _avg(pools["profondita"]),
        "volume_scavo_teorico": _sum(pools["volume_scavo_teorico"]),
        "volume_cls_teorico":   vol_teorico,
        "volume_cls_reale":     vol_reale,
        "delta_cls":            delta,
        "delta_cls_pct":        delta_pct,
        "superficie":           _sum(pools["superficie"]),
        "ml":                   _sum(pools["ml"]),
        "cls_reale_coverage":   len(pools["volume_cls_reale"]),
    }


def _safe_add(a: Optional[float], b: Optional[float]) -> Optional[float]:
    """Add two nullable floats. None only when both are None."""
    if a is None and b is None:
        return None
    return round((a or 0.0) + (b or 0.0), 2)


def _pct(done: int, total: int) -> int:
    if not total:
        return 0
    return min(100, round(done / total * 100))


# ── Public API ────────────────────────────────────────────────────────────────

def compute_site_production(site, fiches: list) -> dict[str, Any]:
    """
    Aggregate production statistics for a site.
    Input: site ORM object + list of already-loaded Fiche ORM objects.
    Output: structured dict for Jinja templates.

    Principle: zero economic data, zero invented values.
    '—' is shown (via fmt()) when a value cannot be derived from existing data.
    """
    from models.entities import FicheTypeEnum

    prod_fiches = [f for f in fiches if f.fiche_type == FicheTypeEnum.produzione]

    tipo_paratia = {"paratia", "paroi", "parois", "panneau"}
    tipo_palo    = {"palo", "pieu", "pieux"}

    paratie = [f for f in prod_fiches if (f.tipologia_scavo or "").lower() in tipo_paratia]
    pali    = [f for f in prod_fiches if (f.tipologia_scavo or "").lower() in tipo_palo]

    paratie_stats = _aggregate_group(paratie)
    pali_stats    = _aggregate_group(pali)

    target_paratie = site.numero_totale_paratie or 0
    target_pali    = site.numero_totale_pali    or 0

    vol_scavo_tot = _safe_add(
        paratie_stats["volume_scavo_teorico"],
        pali_stats["volume_scavo_teorico"],
    )
    vol_cls_teorico_tot = _safe_add(
        paratie_stats["volume_cls_teorico"],
        pali_stats["volume_cls_teorico"],
    )
    vol_cls_reale_tot = _safe_add(
        paratie_stats["volume_cls_reale"],
        pali_stats["volume_cls_reale"],
    )
    delta_tot: Optional[float] = None
    delta_pct_tot: Optional[float] = None
    if vol_cls_teorico_tot is not None and vol_cls_reale_tot is not None:
        delta_tot = round(vol_cls_reale_tot - vol_cls_teorico_tot, 2)
        if vol_cls_teorico_tot != 0:
            delta_pct_tot = round(delta_tot / vol_cls_teorico_tot * 100, 1)

    return {
        "has_data": len(prod_fiches) > 0,
        "total_fiches_produzione": len(prod_fiches),
        "paratie": {
            **paratie_stats,
            "target":         target_paratie,
            "avanzamento_pct": _pct(paratie_stats["count"], target_paratie),
        },
        "pali": {
            **pali_stats,
            "target":         target_pali,
            "avanzamento_pct": _pct(pali_stats["count"], target_pali),
        },
        "totale": {
            "count":                len(prod_fiches),
            "volume_scavo_teorico": vol_scavo_tot,
            "volume_cls_teorico":   vol_cls_teorico_tot,
            "volume_cls_reale":     vol_cls_reale_tot,
            "delta_cls":            delta_tot,
            "delta_cls_pct":        delta_pct_tot,
        },
        # expose fmt() so templates can call production_stats.fmt(value, ...)
        "fmt": fmt,
    }
