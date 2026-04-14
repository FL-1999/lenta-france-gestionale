from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload

from auth import get_current_active_user_html
from database import get_db
from models import (
    Site,
    SiteEconomicCategoryEnum,
    SiteEconomicEntry,
    SiteEconomicEntryTypeEnum,
    SiteLaborCostEntry,
    User,
)
from permissions import has_perm
from template_context import build_template_context, register_manager_badges
from utils.site_economics import (
    build_daily_trend_series,
    calculate_daily_totals,
    calculate_monthly_totals,
    calculate_period_totals,
    calculate_weekly_totals,
    compute_labor_flags,
    parse_iso_date,
    resolve_period,
    serialize_timeframe_filters,
    week_bounds,
    month_bounds,
)


router = APIRouter(tags=["manager-economics"])
templates = Jinja2Templates(directory="templates")
register_manager_badges(templates)

TIMEFRAME_OPTIONS = {
    "day": "Giorno",
    "week": "Settimana",
    "month": "Mese",
    "custom": "Intervallo",
}

CATEGORY_LABELS = {
    SiteEconomicCategoryEnum.ricavi_previsti: "Ricavi previsti",
    SiteEconomicCategoryEnum.ricavi_fatturati: "Ricavi fatturati",
    SiteEconomicCategoryEnum.ricavi_maturati: "Ricavi maturati",
    SiteEconomicCategoryEnum.materiali: "Materiali",
    SiteEconomicCategoryEnum.trasporti: "Trasporti",
    SiteEconomicCategoryEnum.mezzi: "Mezzi",
    SiteEconomicCategoryEnum.attrezzature: "Attrezzature",
    SiteEconomicCategoryEnum.manodopera: "Manodopera",
    SiteEconomicCategoryEnum.altri_costi: "Altri costi",
}

COST_CATEGORY_OPTIONS = [
    SiteEconomicCategoryEnum.materiali,
    SiteEconomicCategoryEnum.trasporti,
    SiteEconomicCategoryEnum.mezzi,
    SiteEconomicCategoryEnum.attrezzature,
    SiteEconomicCategoryEnum.altri_costi,
]

REVENUE_CATEGORY_OPTIONS = [
    SiteEconomicCategoryEnum.ricavi_previsti,
    SiteEconomicCategoryEnum.ricavi_fatturati,
    SiteEconomicCategoryEnum.ricavi_maturati,
]

TREND_CATEGORY_MAP = {
    "revenues": {
        "label": "Ricavi",
        "categories": {
            SiteEconomicCategoryEnum.ricavi_previsti,
            SiteEconomicCategoryEnum.ricavi_fatturati,
            SiteEconomicCategoryEnum.ricavi_maturati,
        },
    },
    "labor": {
        "label": "Manodopera",
        "categories": {SiteEconomicCategoryEnum.manodopera},
    },
    "materials": {
        "label": "Materiali",
        "categories": {SiteEconomicCategoryEnum.materiali},
    },
    "logistics": {
        "label": "Mezzi / trasporti",
        "categories": {SiteEconomicCategoryEnum.trasporti, SiteEconomicCategoryEnum.mezzi},
    },
    "equipment": {
        "label": "Attrezzature",
        "categories": {SiteEconomicCategoryEnum.attrezzature},
    },
    "other_costs": {
        "label": "Altri costi",
        "categories": {SiteEconomicCategoryEnum.altri_costi},
    },
}

WEEKDAY_LABELS = {
    0: "feriale",
    1: "feriale",
    2: "feriale",
    3: "feriale",
    4: "feriale",
    5: "sabato",
    6: "domenica",
}


def _ensure_economics_access(user: User) -> None:
    if not has_perm(user, "economics.read"):
        raise HTTPException(status_code=403, detail="Permessi insufficienti per l'area economica")


def _ensure_economics_manage(user: User) -> None:
    if not has_perm(user, "economics.manage"):
        raise HTTPException(status_code=403, detail="Permessi insufficienti per modificare i dati economici")


def _bucket_key(value: date, group_by: str) -> tuple[str, str]:
    if group_by == "day":
        return value.isoformat(), value.strftime("%d/%m/%Y")
    if group_by == "week":
        monday = value - timedelta(days=value.weekday())
        sunday = monday + timedelta(days=6)
        return monday.isoformat(), f"{monday:%d/%m} - {sunday:%d/%m}"
    month_start = value.replace(day=1)
    return month_start.isoformat(), month_start.strftime("%m/%Y")


def _default_group_for_timeframe(timeframe: str) -> str:
    return {
        "day": "day",
        "week": "day",
        "month": "week",
        "custom": "month",
    }.get(timeframe, "week")


def _safe_pct(numerator: float, denominator: float) -> float:
    if not denominator:
        return 0.0
    return round((numerator / denominator) * 100, 2)


def _sum_progress_percent(progress_summary: dict[str, dict[str, Any]]) -> float:
    keys = [
        "installazione_cantiere",
        "cordoli",
        "paratie",
        "pozzi_pompaggio",
        "rabotage",
        "puntoni",
    ]
    values = [float(progress_summary.get(key, {}).get("percent", 0) or 0) for key in keys]
    return round(sum(values) / len(keys), 2) if values else 0.0


def _build_progress_summary(site: Site) -> dict[str, dict[str, Any]]:
    def _pct(done: float, total: float) -> float:
        if total <= 0:
            return 0.0
        return round(min(max((done / total) * 100, 0), 100), 2)

    strut_levels = list(site.strut_levels or [])
    strut_total = sum(int(level.total_struts_level or 0) for level in strut_levels)
    strut_done = sum(int(level.done_struts_level or 0) for level in strut_levels)

    return {
        "installazione_cantiere": {"percent": float(site.installazione_cantiere_pct or 0)},
        "cordoli": {"percent": _pct(float(site.cordoli_done_m or 0), float(site.cordoli_total_m or 0))},
        "paratie": {"percent": _pct(float(site.paratie_done_panels or 0), float(site.paratie_total_panels or 0))},
        "pozzi_pompaggio": {"percent": float(site.pozzi_pompaggio_pct or 0)},
        "rabotage": {"percent": float(site.rabotage_pct or 0)},
        "puntoni": {"percent": _pct(float(strut_done), float(strut_total))},
    }


def _normalize_entry_amount(raw_amount: str) -> float:
    normalized = (raw_amount or "").strip().replace("€", "").replace(" ", "").replace(",", ".")
    value = float(normalized)
    if value < 0:
        raise ValueError("Importo negativo non consentito")
    return round(value, 2)


def _label_for_category(category: SiteEconomicCategoryEnum | str) -> str:
    if isinstance(category, str):
        category = SiteEconomicCategoryEnum(category)
    return CATEGORY_LABELS.get(category, category.value.replace("_", " ").title())


def _validate_entry_type_and_category(
    entry_type: SiteEconomicEntryTypeEnum,
    category: SiteEconomicCategoryEnum,
) -> None:
    if entry_type == SiteEconomicEntryTypeEnum.revenue and category not in REVENUE_CATEGORY_OPTIONS:
        raise ValueError("Categoria non valida per un ricavo")
    if entry_type == SiteEconomicEntryTypeEnum.cost and category not in COST_CATEGORY_OPTIONS:
        raise ValueError("Categoria non valida per un costo")


def _serialize_economic_entry(entry: SiteEconomicEntry) -> dict[str, Any]:
    return {
        "id": entry.id,
        "entry_date": entry.entry_date,
        "entry_type": entry.entry_type.value,
        "category": entry.category.value,
        "category_label": _label_for_category(entry.category),
        "amount": round(float(entry.amount or 0), 2),
        "description": entry.description or "",
        "notes": entry.notes or "",
        "created_at": entry.created_at,
        "created_by_name": (entry.created_by.full_name or entry.created_by.email) if entry.created_by else "Sistema",
        "updated_at": entry.updated_at,
        "updated_by_name": (entry.updated_by.full_name or entry.updated_by.email) if entry.updated_by else None,
    }


def _build_site_economic_snapshot(
    site: Site,
    start_date: date,
    end_date: date,
    group_by: str,
    timeframe: str,
) -> dict[str, Any]:
    entries = [
        entry for entry in (site.economic_entries or [])
        if start_date <= entry.entry_date <= end_date
    ]
    labor_entries = [
        entry for entry in (site.labor_cost_entries or [])
        if start_date <= entry.work_date <= end_date
    ]
    active_labor_entries = [entry for entry in labor_entries if entry.is_active]

    revenue_totals = defaultdict(float)
    cost_totals = defaultdict(float)

    for entry in entries:
        bucket = revenue_totals if entry.entry_type == SiteEconomicEntryTypeEnum.revenue else cost_totals
        bucket[entry.category] += float(entry.amount or 0)

    labor_total = round(sum(float(entry.total_cost or 0) for entry in active_labor_entries), 2)
    cost_totals[SiteEconomicCategoryEnum.manodopera] += labor_total

    ricavi_previsti = round(revenue_totals[SiteEconomicCategoryEnum.ricavi_previsti], 2)
    ricavi_fatturati = round(revenue_totals[SiteEconomicCategoryEnum.ricavi_fatturati], 2)
    ricavi_maturati = round(revenue_totals[SiteEconomicCategoryEnum.ricavi_maturati], 2)

    cost_breakdown = {
        "materiali": round(cost_totals[SiteEconomicCategoryEnum.materiali], 2),
        "trasporti": round(cost_totals[SiteEconomicCategoryEnum.trasporti], 2),
        "mezzi": round(cost_totals[SiteEconomicCategoryEnum.mezzi], 2),
        "attrezzature": round(cost_totals[SiteEconomicCategoryEnum.attrezzature], 2),
        "manodopera": round(cost_totals[SiteEconomicCategoryEnum.manodopera], 2),
        "altri_costi": round(cost_totals[SiteEconomicCategoryEnum.altri_costi], 2),
    }
    cost_breakdown["mezzi_trasporti"] = round(cost_breakdown["trasporti"] + cost_breakdown["mezzi"], 2)

    total_costs = round(sum(cost_breakdown[key] for key in ["materiali", "trasporti", "mezzi", "attrezzature", "manodopera", "altri_costi"]), 2)
    gross_margin = round(ricavi_maturati - (total_costs - cost_breakdown["altri_costi"]), 2)
    net_profit = round(ricavi_fatturati - total_costs, 2)
    margin_pct = _safe_pct(net_profit, ricavi_fatturati or ricavi_maturati or ricavi_previsti)

    progress_summary = _build_progress_summary(site)
    operational_progress_pct = _sum_progress_percent(progress_summary)
    cost_vs_expected_pct = _safe_pct(total_costs, ricavi_previsti)
    earned_vs_expected_pct = _safe_pct(ricavi_maturati or ricavi_fatturati, ricavi_previsti)

    all_series = []
    for entry in entries:
        all_series.append({
            "date": entry.entry_date,
            "category": entry.category,
            "amount": float(entry.amount or 0),
        })
    for entry in active_labor_entries:
        all_series.append({
            "date": entry.work_date,
            "category": SiteEconomicCategoryEnum.manodopera,
            "amount": float(entry.total_cost or 0),
        })

    buckets: dict[str, dict[str, Any]] = {}
    for item in sorted(all_series, key=lambda row: row["date"]):
        bucket_id, label = _bucket_key(item["date"], group_by)
        bucket = buckets.setdefault(
            bucket_id,
            {
                "label": label,
                **{trend_key: 0.0 for trend_key in TREND_CATEGORY_MAP},
            },
        )
        for trend_key, trend_conf in TREND_CATEGORY_MAP.items():
            if item["category"] in trend_conf["categories"]:
                bucket[trend_key] += float(item["amount"] or 0)

    trend = []
    for bucket_id in sorted(buckets):
        row = buckets[bucket_id]
        total_cost_bucket = sum(row[key] for key in ["labor", "materials", "logistics", "equipment", "other_costs"])
        margin_bucket = row["revenues"] - total_cost_bucket
        trend.append(
            {
                "label": row["label"],
                "revenues": round(row["revenues"], 2),
                "labor": round(row["labor"], 2),
                "materials": round(row["materials"], 2),
                "logistics": round(row["logistics"], 2),
                "equipment": round(row["equipment"], 2),
                "other_costs": round(row["other_costs"], 2),
                "total_costs": round(total_cost_bucket, 2),
                "profit": round(margin_bucket, 2),
            }
        )

    recent_entries = sorted(entries, key=lambda item: (item.entry_date, item.id), reverse=True)
    recent_labor_entries = sorted(labor_entries, key=lambda item: (item.work_date, item.id), reverse=True)
    today = date.today()
    current_week_start, current_week_end = week_bounds(today)
    current_month_start, current_month_end = month_bounds(today)
    daily_trend = build_daily_trend_series(site.economic_entries or [], site.labor_cost_entries or [], start_date, end_date)

    return {
        "site": site,
        "period": {"start": start_date, "end": end_date, "label": f"{start_date:%d/%m/%Y} → {end_date:%d/%m/%Y}"},
        "filters": serialize_timeframe_filters(start_date, end_date, timeframe),
        "metrics": {
            "ricavi_previsti": ricavi_previsti,
            "ricavi_fatturati": ricavi_fatturati,
            "ricavi_maturati": ricavi_maturati,
            "costi_totali": total_costs,
            "margine_lordo": gross_margin,
            "utile_perdita": net_profit,
            "margine_pct": margin_pct,
            "costo_personale": cost_breakdown["manodopera"],
            "costo_materiali": cost_breakdown["materiali"],
            "costo_mezzi_trasporti": cost_breakdown["mezzi_trasporti"],
        },
        "report_filters": {
            "oggi": serialize_timeframe_filters(today, today, "day"),
            "settimana_corrente": serialize_timeframe_filters(current_week_start, current_week_end, "week"),
            "mese_corrente": serialize_timeframe_filters(current_month_start, current_month_end, "month"),
            "intervallo_personalizzato": serialize_timeframe_filters(start_date, end_date, "custom"),
        },
        "period_summaries": {
            "oggi": calculate_daily_totals(site.economic_entries or [], site.labor_cost_entries or [], today),
            "settimana_corrente": calculate_weekly_totals(site.economic_entries or [], site.labor_cost_entries or [], today),
            "mese_corrente": calculate_monthly_totals(site.economic_entries or [], site.labor_cost_entries or [], today),
            "periodo_selezionato": calculate_period_totals(site.economic_entries or [], site.labor_cost_entries or [], start_date, end_date),
        },
        "cost_breakdown": cost_breakdown,
        "sal": {
            "operational_progress_pct": operational_progress_pct,
            "cost_vs_expected_pct": cost_vs_expected_pct,
            "earned_vs_expected_pct": earned_vs_expected_pct,
            "current_margin": net_profit,
            "costs_sustained": total_costs,
            "expected_revenues": ricavi_previsti,
            "earned_revenues": ricavi_maturati or ricavi_fatturati,
        },
        "trend": trend,
        "trend_series": daily_trend,
        "labor_entries": [
            {
                "id": entry.id,
                "work_date": entry.work_date,
                "worker_count": entry.worker_count,
                "unit_cost": round(float(entry.unit_cost or 0), 2),
                "total_cost": round(float(entry.total_cost or 0), 2),
                "is_weekend": bool(entry.is_weekend),
                "is_active": bool(entry.is_active),
                "day_type": WEEKDAY_LABELS.get(entry.work_date.weekday(), "feriale"),
                "notes": entry.notes or "",
            }
            for entry in recent_labor_entries
        ],
        "economic_entries": [
            _serialize_economic_entry(entry)
            for entry in recent_entries
        ],
    }


@router.get("/manager/economics", response_class=HTMLResponse, name="manager_economics_dashboard")
def manager_economics_dashboard(
    request: Request,
    timeframe: str = Query("month"),
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    current_user: User = Depends(get_current_active_user_html),
    db: Session = Depends(get_db),
):
    _ensure_economics_access(current_user)
    period_start, period_end, timeframe = resolve_period(timeframe, start_date, end_date)
    group_by = _default_group_for_timeframe(timeframe)

    sites = (
        db.query(Site)
        .options(joinedload(Site.strut_levels), joinedload(Site.economic_entries), joinedload(Site.labor_cost_entries))
        .order_by(Site.name.asc())
        .all()
    )

    snapshots = [_build_site_economic_snapshot(site, period_start, period_end, group_by, timeframe) for site in sites]

    totals = {
        "ricavi_previsti": round(sum(item["metrics"]["ricavi_previsti"] for item in snapshots), 2),
        "ricavi_fatturati": round(sum(item["metrics"]["ricavi_fatturati"] for item in snapshots), 2),
        "ricavi_maturati": round(sum(item["metrics"]["ricavi_maturati"] for item in snapshots), 2),
        "costi_totali": round(sum(item["metrics"]["costi_totali"] for item in snapshots), 2),
        "costo_personale": round(sum(item["metrics"]["costo_personale"] for item in snapshots), 2),
        "costo_materiali": round(sum(item["metrics"]["costo_materiali"] for item in snapshots), 2),
        "costo_mezzi_trasporti": round(sum(item["metrics"]["costo_mezzi_trasporti"] for item in snapshots), 2),
        "utile_perdita": round(sum(item["metrics"]["utile_perdita"] for item in snapshots), 2),
    }
    totals["margine_pct"] = _safe_pct(totals["utile_perdita"], totals["ricavi_fatturati"] or totals["ricavi_maturati"] or totals["ricavi_previsti"])

    category_totals = {
        "materiali": round(sum(item["cost_breakdown"]["materiali"] for item in snapshots), 2),
        "trasporti": round(sum(item["cost_breakdown"]["trasporti"] for item in snapshots), 2),
        "mezzi": round(sum(item["cost_breakdown"]["mezzi"] for item in snapshots), 2),
        "attrezzature": round(sum(item["cost_breakdown"]["attrezzature"] for item in snapshots), 2),
        "manodopera": round(sum(item["cost_breakdown"]["manodopera"] for item in snapshots), 2),
        "altri_costi": round(sum(item["cost_breakdown"]["altri_costi"] for item in snapshots), 2),
    }

    trend_totals: dict[str, dict[str, float | str]] = {}
    for snapshot in snapshots:
        for row in snapshot["trend"]:
            bucket = trend_totals.setdefault(
                row["label"],
                {
                    "label": row["label"],
                    "revenues": 0.0,
                    "labor": 0.0,
                    "materials": 0.0,
                    "logistics": 0.0,
                    "equipment": 0.0,
                    "other_costs": 0.0,
                    "total_costs": 0.0,
                    "profit": 0.0,
                },
            )
            for key in ["revenues", "labor", "materials", "logistics", "equipment", "other_costs", "total_costs", "profit"]:
                bucket[key] += float(row[key])

    trend = [
        {
            **row,
            **{key: round(float(row[key]), 2) for key in ["revenues", "labor", "materials", "logistics", "equipment", "other_costs", "total_costs", "profit"]},
        }
        for _, row in sorted(trend_totals.items())
    ]

    return templates.TemplateResponse(
        request,
        "manager/economics_dashboard.html",
        build_template_context(
            request,
            current_user,
            snapshots=snapshots,
            totals=totals,
            category_totals=category_totals,
            trend=trend,
            timeframe=timeframe,
            timeframe_options=TIMEFRAME_OPTIONS,
            filters=serialize_timeframe_filters(period_start, period_end, timeframe),
        ),
    )


@router.get("/manager/cantieri/{site_id}/economics", response_class=HTMLResponse, name="manager_site_economics_detail")
def manager_site_economics_detail(
    request: Request,
    site_id: int,
    timeframe: str = Query("month"),
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    current_user: User = Depends(get_current_active_user_html),
    db: Session = Depends(get_db),
):
    _ensure_economics_access(current_user)
    period_start, period_end, timeframe = resolve_period(timeframe, start_date, end_date)
    group_by = _default_group_for_timeframe(timeframe)

    site = (
        db.query(Site)
        .options(joinedload(Site.strut_levels), joinedload(Site.economic_entries), joinedload(Site.labor_cost_entries))
        .filter(Site.id == site_id)
        .first()
    )
    if not site:
        raise HTTPException(status_code=404, detail="Cantiere non trovato")

    snapshot = _build_site_economic_snapshot(site, period_start, period_end, group_by, timeframe)
    can_manage = has_perm(current_user, "economics.manage")

    return templates.TemplateResponse(
        request,
        "manager/site_economics_detail.html",
        build_template_context(
            request,
            current_user,
            snapshot=snapshot,
            site=site,
            timeframe=timeframe,
            timeframe_options=TIMEFRAME_OPTIONS,
            filters=serialize_timeframe_filters(period_start, period_end, timeframe),
            category_labels={item.value: label for item, label in CATEGORY_LABELS.items()},
            cost_category_options=COST_CATEGORY_OPTIONS,
            revenue_category_options=REVENUE_CATEGORY_OPTIONS,
            can_manage=can_manage,
        ),
    )


@router.get("/manager/cantieri/{site_id}/economics/trend-data", name="manager_site_economics_trend_data")
def manager_site_economics_trend_data(
    site_id: int,
    timeframe: str = Query("month"),
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    current_user: User = Depends(get_current_active_user_html),
    db: Session = Depends(get_db),
):
    _ensure_economics_access(current_user)
    period_start, period_end, _ = resolve_period(timeframe, start_date, end_date)

    site = (
        db.query(Site)
        .options(joinedload(Site.economic_entries), joinedload(Site.labor_cost_entries))
        .filter(Site.id == site_id)
        .first()
    )
    if not site:
        raise HTTPException(status_code=404, detail="Cantiere non trovato")

    return {
        "site_id": site.id,
        "site_name": site.name,
        "timeframe": timeframe,
        "start_date": period_start.isoformat(),
        "end_date": period_end.isoformat(),
        "series": build_daily_trend_series(site.economic_entries or [], site.labor_cost_entries or [], period_start, period_end),
    }


@router.post("/manager/cantieri/{site_id}/economics/entries", name="manager_site_economics_entry_create")
def manager_site_economics_entry_create(
    site_id: int,
    entry_date: str = Form(...),
    entry_type: str = Form(...),
    category: str = Form(...),
    amount: str = Form(...),
    description: str | None = Form(None),
    notes: str | None = Form(None),
    timeframe: str = Form("month"),
    start_date: str | None = Form(None),
    end_date: str | None = Form(None),
    current_user: User = Depends(get_current_active_user_html),
    db: Session = Depends(get_db),
):
    _ensure_economics_manage(current_user)
    site = db.query(Site.id).filter(Site.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="Cantiere non trovato")

    try:
        parsed_date = datetime.strptime(entry_date, "%Y-%m-%d").date()
        parsed_type = SiteEconomicEntryTypeEnum(entry_type)
        parsed_category = SiteEconomicCategoryEnum(category)
        parsed_amount = _normalize_entry_amount(amount)
        _validate_entry_type_and_category(parsed_type, parsed_category)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Dati economici non validi")

    db.add(
        SiteEconomicEntry(
            site_id=site_id,
            entry_date=parsed_date,
            entry_type=parsed_type,
            category=parsed_category,
            amount=parsed_amount,
            description=(description or "").strip() or None,
            notes=(notes or "").strip() or None,
            created_by_id=getattr(current_user, "id", None),
            updated_by_id=getattr(current_user, "id", None),
        )
    )
    db.commit()
    return RedirectResponse(
        url=f"/manager/cantieri/{site_id}/economics?timeframe={timeframe}&start_date={start_date or ''}&end_date={end_date or ''}",
        status_code=303,
    )


@router.put("/manager/cantieri/{site_id}/economics/entries/{entry_id}", name="manager_site_economics_entry_update")
@router.patch("/manager/cantieri/{site_id}/economics/entries/{entry_id}")
def manager_site_economics_entry_update(
    site_id: int,
    entry_id: int,
    entry_date: str = Form(...),
    entry_type: str = Form(...),
    category: str = Form(...),
    amount: str = Form(...),
    description: str | None = Form(None),
    notes: str | None = Form(None),
    current_user: User = Depends(get_current_active_user_html),
    db: Session = Depends(get_db),
):
    _ensure_economics_manage(current_user)
    entry = (
        db.query(SiteEconomicEntry)
        .options(joinedload(SiteEconomicEntry.created_by), joinedload(SiteEconomicEntry.updated_by))
        .filter(SiteEconomicEntry.id == entry_id, SiteEconomicEntry.site_id == site_id)
        .first()
    )
    if not entry:
        raise HTTPException(status_code=404, detail="Movimento economico non trovato")

    try:
        parsed_date = datetime.strptime(entry_date, "%Y-%m-%d").date()
        parsed_type = SiteEconomicEntryTypeEnum(entry_type)
        parsed_category = SiteEconomicCategoryEnum(category)
        parsed_amount = _normalize_entry_amount(amount)
        _validate_entry_type_and_category(parsed_type, parsed_category)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Dati economici non validi")

    entry.entry_date = parsed_date
    entry.entry_type = parsed_type
    entry.category = parsed_category
    entry.amount = parsed_amount
    entry.description = (description or "").strip() or None
    entry.notes = (notes or "").strip() or None
    entry.updated_by_id = getattr(current_user, "id", None)
    db.commit()
    db.refresh(entry)

    return {"ok": True, "entry": _serialize_economic_entry(entry)}


@router.delete("/manager/cantieri/{site_id}/economics/entries/{entry_id}", name="manager_site_economics_entry_delete")
def manager_site_economics_entry_delete(
    site_id: int,
    entry_id: int,
    current_user: User = Depends(get_current_active_user_html),
    db: Session = Depends(get_db),
):
    _ensure_economics_manage(current_user)
    entry = (
        db.query(SiteEconomicEntry)
        .filter(SiteEconomicEntry.id == entry_id, SiteEconomicEntry.site_id == site_id)
        .first()
    )
    if not entry:
        raise HTTPException(status_code=404, detail="Movimento economico non trovato")

    db.delete(entry)
    db.commit()
    return {"ok": True, "deleted_id": entry_id}


@router.post("/manager/cantieri/{site_id}/economics/labor", name="manager_site_economics_labor_create")
def manager_site_economics_labor_create(
    site_id: int,
    work_date: str = Form(...),
    worker_count: int = Form(...),
    unit_cost: str = Form(...),
    is_active: str | None = Form(None),
    notes: str | None = Form(None),
    timeframe: str = Form("month"),
    start_date: str | None = Form(None),
    end_date: str | None = Form(None),
    current_user: User = Depends(get_current_active_user_html),
    db: Session = Depends(get_db),
):
    _ensure_economics_manage(current_user)
    site = db.query(Site.id).filter(Site.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="Cantiere non trovato")

    try:
        parsed_date = datetime.strptime(work_date, "%Y-%m-%d").date()
        parsed_unit_cost = _normalize_entry_amount(unit_cost)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Costo manodopera non valido")

    if worker_count < 0:
        raise HTTPException(status_code=400, detail="Numero persone non valido")

    parsed_is_weekend, parsed_is_active = compute_labor_flags(parsed_date, is_active in {"1", "true", "True", "on", "yes"})

    record = (
        db.query(SiteLaborCostEntry)
        .filter(SiteLaborCostEntry.site_id == site_id, SiteLaborCostEntry.work_date == parsed_date)
        .first()
    )
    if record is None:
        record = SiteLaborCostEntry(site_id=site_id, work_date=parsed_date, created_by_id=getattr(current_user, "id", None))
        db.add(record)

    record.worker_count = worker_count
    record.unit_cost = parsed_unit_cost
    record.is_weekend = parsed_is_weekend
    record.is_active = parsed_is_active
    record.notes = (notes or "").strip() or None
    db.commit()

    return RedirectResponse(
        url=f"/manager/cantieri/{site_id}/economics?timeframe={timeframe}&start_date={start_date or ''}&end_date={end_date or ''}#labor-costs",
        status_code=303,
    )
