from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
import json
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload

from auth import get_current_active_user_html
from database import get_db
from models import (
    Fiche,
    PersonalePresenza,
    Site,
    SiteEconomicAutoParams,
    SiteEconomicBudget,
    SiteEconomicCategoryEnum,
    SiteEconomicEntry,
    SiteEconomicEntryTypeEnum,
    SiteLaborCostEntry,
    User,
)
from permissions import can_view_site_margin, has_perm
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

BUDGET_CATEGORY_FIELDS = [
    ("materiali", "materiali_previsti", "Materiali"),
    ("manodopera", "manodopera_prevista", "Manodopera"),
    ("trasporti", "trasporti_previsti", "Trasporti"),
    ("mezzi", "mezzi_previsti", "Mezzi"),
    ("attrezzature", "attrezzature_previste", "Attrezzature"),
    ("altri_costi", "altri_costi_previsti", "Altri costi"),
]

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


def _serialize_site_budget(budget: SiteEconomicBudget | None) -> dict[str, Any]:
    if not budget:
        return {
            "exists": False,
            "ricavo_previsto": 0.0,
            "materiali_previsti": 0.0,
            "manodopera_prevista": 0.0,
            "trasporti_previsti": 0.0,
            "mezzi_previsti": 0.0,
            "attrezzature_previste": 0.0,
            "altri_costi_previsti": 0.0,
            "totale_costi_previsti": 0.0,
            "margine_previsto": 0.0,
            "note": "",
            "created_at": None,
            "updated_at": None,
            "created_by_name": "—",
            "updated_by_name": "—",
        }
    totale_costi_previsti = round(
        float(budget.materiali_previsti or 0)
        + float(budget.manodopera_prevista or 0)
        + float(budget.trasporti_previsti or 0)
        + float(budget.mezzi_previsti or 0)
        + float(budget.attrezzature_previste or 0)
        + float(budget.altri_costi_previsti or 0),
        2,
    )
    ricavo_previsto = round(float(budget.ricavo_previsto or 0), 2)
    return {
        "exists": True,
        "ricavo_previsto": ricavo_previsto,
        "materiali_previsti": round(float(budget.materiali_previsti or 0), 2),
        "manodopera_prevista": round(float(budget.manodopera_prevista or 0), 2),
        "trasporti_previsti": round(float(budget.trasporti_previsti or 0), 2),
        "mezzi_previsti": round(float(budget.mezzi_previsti or 0), 2),
        "attrezzature_previste": round(float(budget.attrezzature_previste or 0), 2),
        "altri_costi_previsti": round(float(budget.altri_costi_previsti or 0), 2),
        "totale_costi_previsti": totale_costi_previsti,
        "margine_previsto": round(ricavo_previsto - totale_costi_previsti, 2),
        "note": budget.note or "",
        "created_at": budget.created_at,
        "updated_at": budget.updated_at,
        "created_by_name": (budget.created_by.full_name or budget.created_by.email) if budget.created_by else "Sistema",
        "updated_by_name": (budget.updated_by.full_name or budget.updated_by.email) if budget.updated_by else "—",
    }


def _normalize_material_key(value: str | None) -> str:
    return (value or "").strip().lower()


def _parse_material_prices(raw: str | None) -> dict[str, float]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    parsed: dict[str, float] = {}
    for key, value in payload.items():
        material_key = _normalize_material_key(str(key))
        if not material_key:
            continue
        try:
            parsed[material_key] = round(max(float(value), 0.0), 2)
        except (TypeError, ValueError):
            continue
    return parsed


def _serialize_auto_params(params: SiteEconomicAutoParams | None) -> dict[str, Any]:
    if not params:
        return {
            "configured": False,
            "costo_manodopera_persona_giorno": 0.0,
            "costo_cemento_mc": 0.0,
            "costo_ferro_ton": 0.0,
            "costo_ferro_kg": 0.0,
            "altri_prezzi": {},
            "manual_material_entries_override_auto": True,
            "created_at": None,
            "updated_at": None,
            "created_by_name": "—",
            "updated_by_name": "—",
        }
    return {
        "configured": True,
        "costo_manodopera_persona_giorno": round(float(params.costo_manodopera_persona_giorno or 0), 2),
        "costo_cemento_mc": round(float(params.costo_cemento_mc or 0), 2),
        "costo_ferro_ton": round(float(params.costo_ferro_ton or 0), 2),
        "costo_ferro_kg": round(float(params.costo_ferro_kg or 0), 2),
        "altri_prezzi": _parse_material_prices(params.altri_prezzi_json),
        "manual_material_entries_override_auto": bool(params.manual_material_entries_override_auto),
        "created_at": params.created_at,
        "updated_at": params.updated_at,
        "created_by_name": (params.created_by.full_name or params.created_by.email) if params.created_by else "Sistema",
        "updated_by_name": (params.updated_by.full_name or params.updated_by.email) if params.updated_by else "—",
    }


def _serialize_material_prices(prices: dict[str, float]) -> str:
    normalized = {key: round(max(float(value), 0.0), 2) for key, value in prices.items() if key}
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True)


def _compute_auto_labor_costs(
    site: Site,
    auto_params: SiteEconomicAutoParams | None,
    attendance_rows: list[PersonalePresenza],
    start_date: date,
    end_date: date,
) -> tuple[list[dict[str, Any]], dict[date, float], float]:
    default_unit_cost = round(float(getattr(auto_params, "costo_manodopera_persona_giorno", 0.0) or 0.0), 2)
    if default_unit_cost <= 0:
        return [], {}, 0.0

    attendance = [row for row in attendance_rows if row.status == "WORK"]
    per_day_workers: dict[date, int] = defaultdict(int)
    for row in attendance:
        per_day_workers[row.attendance_date] += 1

    overrides = {
        row.work_date: row
        for row in (site.labor_cost_entries or [])
        if row.work_date and start_date <= row.work_date <= end_date
    }
    rows: list[dict[str, Any]] = []
    totals_by_day: dict[date, float] = {}
    all_days = sorted(set(per_day_workers) | set(overrides))
    for work_day in all_days:
        worker_count = int(per_day_workers.get(work_day, 0) or 0)
        unit_cost = default_unit_cost
        total_cost = round(worker_count * unit_cost, 2)
        source = "presenze"
        override_entry = overrides.get(work_day)
        is_active = True
        if override_entry is not None:
            total_cost = round(float(override_entry.total_cost or 0), 2)
            worker_count = int(override_entry.worker_count or 0)
            unit_cost = round(float(override_entry.unit_cost or 0), 2)
            is_active = bool(override_entry.is_active)
            source = "override_manuale"
        if is_active:
            totals_by_day[work_day] = round(float(totals_by_day.get(work_day, 0)) + total_cost, 2)
        rows.append(
            {
                "work_date": work_day,
                "worker_count": worker_count,
                "unit_cost": unit_cost,
                "total_cost": total_cost if is_active else 0.0,
                "is_active": is_active,
                "source": source,
            }
        )

    return rows, totals_by_day, round(sum(totals_by_day.values()), 2)


def _compute_auto_material_costs(
    site: Site,
    auto_params: SiteEconomicAutoParams | None,
    start_date: date,
    end_date: date,
    manual_material_entries: list[SiteEconomicEntry],
) -> tuple[list[dict[str, Any]], dict[date, float], float]:
    unit_price = round(float(getattr(auto_params, "costo_cemento_mc", 0.0) or 0.0), 2)
    if unit_price <= 0:
        return [], {}, 0.0

    manual_days = {entry.entry_date for entry in manual_material_entries}
    rows: list[dict[str, Any]] = []
    totals_by_day: dict[date, float] = defaultdict(float)
    for fiche in (site.fiches or []):
        if not fiche.date or fiche.date < start_date or fiche.date > end_date:
            continue
        qty = round(float(fiche.metri_cubi_gettati or 0.0), 2)
        if qty <= 0:
            continue
        if bool(getattr(auto_params, "manual_material_entries_override_auto", True)) and fiche.date in manual_days:
            continue
        total = round(qty * unit_price, 2)
        totals_by_day[fiche.date] += total
        rows.append(
            {
                "date": fiche.date,
                "material": "cemento",
                "quantity": qty,
                "unit_price": unit_price,
                "total_cost": total,
                "source": "fiches",
                "fiche_id": fiche.id,
            }
        )

    return rows, dict(totals_by_day), round(sum(totals_by_day.values()), 2)


def _build_site_economic_snapshot(
    site: Site,
    attendance_rows: list[PersonalePresenza],
    start_date: date,
    end_date: date,
    group_by: str,
    timeframe: str,
) -> dict[str, Any]:
    entries = [
        entry for entry in (site.economic_entries or [])
        if start_date <= entry.entry_date <= end_date
    ]
    labor_entries = [entry for entry in (site.labor_cost_entries or []) if start_date <= entry.work_date <= end_date]
    budget_data = _serialize_site_budget(getattr(site, "economic_budget", None))
    auto_params_model = getattr(site, "economic_auto_params", None)
    if auto_params_model is None and (
        float(site.labor_cost_per_person or 0) > 0
        or bool(_parse_material_prices(site.material_unit_prices).get("cemento"))
    ):
        legacy = SiteEconomicAutoParams(
            site_id=site.id,
            costo_manodopera_persona_giorno=round(float(site.labor_cost_per_person or 0), 2),
            costo_cemento_mc=round(float(_parse_material_prices(site.material_unit_prices).get("cemento", 0)), 2),
            manual_material_entries_override_auto=bool(site.manual_material_entries_override_auto),
        )
        auto_params_model = legacy
    auto_params = _serialize_auto_params(auto_params_model)

    revenue_totals = defaultdict(float)
    cost_totals = defaultdict(float)

    for entry in entries:
        bucket = revenue_totals if entry.entry_type == SiteEconomicEntryTypeEnum.revenue else cost_totals
        bucket[entry.category] += float(entry.amount or 0)

    manual_material_entries = [
        entry for entry in entries
        if entry.entry_type == SiteEconomicEntryTypeEnum.cost and entry.category == SiteEconomicCategoryEnum.materiali
    ]
    auto_labor_rows, auto_labor_daily, labor_total = _compute_auto_labor_costs(site, auto_params_model, attendance_rows, start_date, end_date)
    auto_material_rows, auto_material_daily, auto_material_total = _compute_auto_material_costs(
        site,
        auto_params_model,
        start_date,
        end_date,
        manual_material_entries,
    )
    manual_cost_breakdown = {
        "materiali": round(cost_totals[SiteEconomicCategoryEnum.materiali], 2),
        "trasporti": round(cost_totals[SiteEconomicCategoryEnum.trasporti], 2),
        "mezzi": round(cost_totals[SiteEconomicCategoryEnum.mezzi], 2),
        "attrezzature": round(cost_totals[SiteEconomicCategoryEnum.attrezzature], 2),
        "manodopera": round(cost_totals[SiteEconomicCategoryEnum.manodopera], 2),
        "altri_costi": round(cost_totals[SiteEconomicCategoryEnum.altri_costi], 2),
    }
    auto_cost_breakdown = {
        "manodopera": round(labor_total, 2),
        "cemento": round(auto_material_total, 2),
        "altri_automatici": 0.0,
    }
    cost_totals[SiteEconomicCategoryEnum.materiali] += auto_cost_breakdown["cemento"]
    cost_totals[SiteEconomicCategoryEnum.manodopera] += auto_cost_breakdown["manodopera"]

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
    margin_pct = _safe_pct(net_profit, ricavi_fatturati or ricavi_maturati or budget_data["ricavo_previsto"])

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
    for day_value, amount in auto_labor_daily.items():
        all_series.append({
            "date": day_value,
            "category": SiteEconomicCategoryEnum.manodopera,
            "amount": float(amount or 0),
        })
    for day_value, amount in auto_material_daily.items():
        all_series.append({
            "date": day_value,
            "category": SiteEconomicCategoryEnum.materiali,
            "amount": float(amount or 0),
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
    today = date.today()
    current_week_start, current_week_end = week_bounds(today)
    current_month_start, current_month_end = month_bounds(today)
    enriched_economic_entries = list(site.economic_entries or [])
    enriched_labor_entries = [entry for entry in (site.labor_cost_entries or []) if False]
    for day_value, amount in auto_labor_daily.items():
        enriched_labor_entries.append(
            SiteLaborCostEntry(
                site_id=site.id,
                work_date=day_value,
                worker_count=0,
                unit_cost=0,
                total_cost=amount,
                is_active=True,
            )
        )
    for day_value, amount in auto_material_daily.items():
        enriched_economic_entries.append(
            SiteEconomicEntry(
                site_id=site.id,
                entry_date=day_value,
                entry_type=SiteEconomicEntryTypeEnum.cost,
                category=SiteEconomicCategoryEnum.materiali,
                amount=amount,
            )
        )
    daily_trend = build_daily_trend_series(enriched_economic_entries, enriched_labor_entries, start_date, end_date)
    real_revenue_total = round(ricavi_fatturati + ricavi_maturati, 2)
    real_total_cost = round(total_costs, 2)
    scostamento_rows = []
    for cost_key, budget_key, label in BUDGET_CATEGORY_FIELDS:
        previsto = round(float(budget_data.get(budget_key, 0) or 0), 2)
        reale = round(float(cost_breakdown.get(cost_key, 0) or 0), 2)
        delta = round(reale - previsto, 2)
        scostamento_rows.append(
            {
                "label": label,
                "previsto": previsto,
                "reale": reale,
                "scostamento": delta,
                "scostamento_pct": _safe_pct(delta, previsto),
            }
        )

    overall_variances = {
        "ricavi": {
            "previsto": budget_data["ricavo_previsto"],
            "reale": real_revenue_total,
        },
        "costi": {
            "previsto": budget_data["totale_costi_previsti"],
            "reale": real_total_cost,
        },
        "margine": {
            "previsto": budget_data["margine_previsto"],
            "reale": round(real_revenue_total - real_total_cost, 2),
        },
    }
    for payload in overall_variances.values():
        payload["scostamento"] = round(payload["reale"] - payload["previsto"], 2)
        payload["scostamento_pct"] = _safe_pct(payload["scostamento"], payload["previsto"])

    warnings: list[str] = []
    if not auto_params["configured"]:
        warnings.append("Parametri economici automatici non ancora configurati.")
    elif auto_params["costo_manodopera_persona_giorno"] <= 0:
        warnings.append("Costo manodopera automatico non configurato: calcolo manodopera a 0.")
    if auto_params["configured"] and auto_params["costo_cemento_mc"] <= 0:
        warnings.append("Costo cemento €/m³ non configurato: calcolo cemento automatico non disponibile.")

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
            "oggi": calculate_daily_totals(enriched_economic_entries, enriched_labor_entries, today),
            "settimana_corrente": calculate_weekly_totals(enriched_economic_entries, enriched_labor_entries, today),
            "mese_corrente": calculate_monthly_totals(enriched_economic_entries, enriched_labor_entries, today),
            "periodo_selezionato": calculate_period_totals(enriched_economic_entries, enriched_labor_entries, start_date, end_date),
        },
        "cost_breakdown": cost_breakdown,
        "auto_cost_breakdown": auto_cost_breakdown,
        "manual_cost_breakdown": manual_cost_breakdown,
        "budget": budget_data,
        "real_summary": {
            "ricavi_reali": real_revenue_total,
            "costi_reali": real_total_cost,
            "margine_reale": round(real_revenue_total - real_total_cost, 2),
        },
        "automatic_real_summary": {
            "costi_automatici": round(sum(auto_cost_breakdown.values()), 2),
        },
        "manual_real_summary": {
            "costi_manuali": round(sum(manual_cost_breakdown.values()), 2),
        },
        "warnings": warnings,
        "variances": {
            "by_category": scostamento_rows,
            "overall": overall_variances,
        },
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
                "work_date": row["work_date"],
                "worker_count": row["worker_count"],
                "unit_cost": row["unit_cost"],
                "total_cost": row["total_cost"],
                "is_active": row["is_active"],
                "day_type": WEEKDAY_LABELS.get(row["work_date"].weekday(), "feriale"),
                "source": row["source"],
            }
            for row in sorted(auto_labor_rows, key=lambda item: item["work_date"], reverse=True)
        ],
        "material_auto_entries": [
            {
                **row,
                "day_type": WEEKDAY_LABELS.get(row["date"].weekday(), "feriale"),
            }
            for row in sorted(auto_material_rows, key=lambda item: (item["date"], item["fiche_id"]), reverse=True)
        ],
        "auto_cost_config": auto_params,
        "economic_entries": [
            _serialize_economic_entry(entry)
            for entry in recent_entries
        ],
    }


def _sanitize_trend_series_for_operational_view(series: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "data": row.get("data"),
            "costi": round(float(row.get("costi", 0) or 0), 2),
        }
        for row in series
    ]


def _filter_snapshot_for_role(snapshot: dict[str, Any], *, include_margin: bool) -> dict[str, Any]:
    if include_margin:
        return snapshot

    filtered_snapshot = dict(snapshot)

    budget = dict(filtered_snapshot.get("budget", {}))
    budget["ricavo_previsto"] = 0.0
    budget["margine_previsto"] = 0.0
    filtered_snapshot["budget"] = budget

    real_summary = dict(filtered_snapshot.get("real_summary", {}))
    real_summary["ricavi_reali"] = 0.0
    real_summary["margine_reale"] = 0.0
    filtered_snapshot["real_summary"] = real_summary

    variances = dict(filtered_snapshot.get("variances", {}))
    overall = dict(variances.get("overall", {}))
    overall.pop("ricavi", None)
    overall.pop("margine", None)
    variances["overall"] = overall
    filtered_snapshot["variances"] = variances

    metrics = dict(filtered_snapshot.get("metrics", {}))
    for key in ["ricavi_previsti", "ricavi_fatturati", "ricavi_maturati", "margine_lordo", "utile_perdita", "margine_pct"]:
        metrics.pop(key, None)
    filtered_snapshot["metrics"] = metrics

    sal = dict(filtered_snapshot.get("sal", {}))
    for key in ["earned_vs_expected_pct", "current_margin", "expected_revenues", "earned_revenues"]:
        sal.pop(key, None)
    filtered_snapshot["sal"] = sal

    filtered_snapshot["trend"] = [
        {
            key: value
            for key, value in row.items()
            if key not in {"revenues", "profit"}
        }
        for row in filtered_snapshot.get("trend", [])
    ]
    filtered_snapshot["trend_series"] = _sanitize_trend_series_for_operational_view(filtered_snapshot.get("trend_series", []))

    return filtered_snapshot


def _filter_dashboard_data_for_role(
    snapshots: list[dict[str, Any]],
    totals: dict[str, Any],
    trend: list[dict[str, Any]],
    *,
    include_margin: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    if include_margin:
        return snapshots, totals, trend

    filtered_snapshots = [_filter_snapshot_for_role(snapshot, include_margin=False) for snapshot in snapshots]

    filtered_totals = {
        key: value
        for key, value in totals.items()
        if key not in {"ricavi_previsti", "ricavi_fatturati", "ricavi_maturati", "utile_perdita", "margine_pct"}
    }

    filtered_trend = [
        {
            key: value
            for key, value in row.items()
            if key not in {"revenues", "profit"}
        }
        for row in trend
    ]

    return filtered_snapshots, filtered_totals, filtered_trend




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
    can_view_margin = can_view_site_margin(current_user)
    period_start, period_end, timeframe = resolve_period(timeframe, start_date, end_date)
    group_by = _default_group_for_timeframe(timeframe)

    sites = (
        db.query(Site)
        .options(
            joinedload(Site.strut_levels),
            joinedload(Site.economic_entries),
            joinedload(Site.fiches),
            joinedload(Site.labor_cost_entries),
            joinedload(Site.economic_budget).joinedload(SiteEconomicBudget.created_by),
            joinedload(Site.economic_budget).joinedload(SiteEconomicBudget.updated_by),
            joinedload(Site.economic_auto_params).joinedload(SiteEconomicAutoParams.created_by),
            joinedload(Site.economic_auto_params).joinedload(SiteEconomicAutoParams.updated_by),
        )
        .order_by(Site.name.asc())
        .all()
    )
    attendance_rows = (
        db.query(PersonalePresenza)
        .filter(
            PersonalePresenza.attendance_date >= period_start,
            PersonalePresenza.attendance_date <= period_end,
        )
        .all()
    )
    attendance_by_site: dict[int, list[PersonalePresenza]] = defaultdict(list)
    for row in attendance_rows:
        if row.site_id is not None:
            attendance_by_site[int(row.site_id)].append(row)

    snapshots = [
        _build_site_economic_snapshot(site, attendance_by_site.get(site.id, []), period_start, period_end, group_by, timeframe)
        for site in sites
    ]

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

    snapshots, totals, trend = _filter_dashboard_data_for_role(
        snapshots,
        totals,
        trend,
        include_margin=can_view_margin,
    )

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
            can_view_site_margin=can_view_margin,
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
    can_view_margin = can_view_site_margin(current_user)
    period_start, period_end, timeframe = resolve_period(timeframe, start_date, end_date)
    group_by = _default_group_for_timeframe(timeframe)

    site = (
        db.query(Site)
        .options(
            joinedload(Site.strut_levels),
            joinedload(Site.economic_entries).joinedload(SiteEconomicEntry.created_by),
            joinedload(Site.economic_entries).joinedload(SiteEconomicEntry.updated_by),
            joinedload(Site.fiches),
            joinedload(Site.labor_cost_entries),
            joinedload(Site.economic_budget).joinedload(SiteEconomicBudget.created_by),
            joinedload(Site.economic_budget).joinedload(SiteEconomicBudget.updated_by),
            joinedload(Site.economic_auto_params).joinedload(SiteEconomicAutoParams.created_by),
            joinedload(Site.economic_auto_params).joinedload(SiteEconomicAutoParams.updated_by),
        )
        .filter(Site.id == site_id)
        .first()
    )
    if not site:
        raise HTTPException(status_code=404, detail="Cantiere non trovato")

    attendance_rows = (
        db.query(PersonalePresenza)
        .filter(
            PersonalePresenza.site_id == site_id,
            PersonalePresenza.attendance_date >= period_start,
            PersonalePresenza.attendance_date <= period_end,
        )
        .all()
    )
    snapshot = _build_site_economic_snapshot(site, attendance_rows, period_start, period_end, group_by, timeframe)
    snapshot = _filter_snapshot_for_role(snapshot, include_margin=can_view_margin)
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
            can_view_site_margin=can_view_margin,
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
    can_view_margin = can_view_site_margin(current_user)
    period_start, period_end, _ = resolve_period(timeframe, start_date, end_date)

    site = (
        db.query(Site)
        .options(joinedload(Site.economic_entries), joinedload(Site.labor_cost_entries))
        .filter(Site.id == site_id)
        .first()
    )
    if not site:
        raise HTTPException(status_code=404, detail="Cantiere non trovato")

    series = build_daily_trend_series(site.economic_entries or [], site.labor_cost_entries or [], period_start, period_end)
    if not can_view_margin:
        series = _sanitize_trend_series_for_operational_view(series)

    return {
        "site_id": site.id,
        "site_name": site.name,
        "timeframe": timeframe,
        "start_date": period_start.isoformat(),
        "end_date": period_end.isoformat(),
        "series": series,
    }


@router.post("/manager/cantieri/{site_id}/economics/budget", name="manager_site_economics_budget_upsert")
def manager_site_economics_budget_upsert(
    site_id: int,
    ricavo_previsto: str = Form("0"),
    materiali_previsti: str = Form("0"),
    manodopera_prevista: str = Form("0"),
    trasporti_previsti: str = Form("0"),
    mezzi_previsti: str = Form("0"),
    attrezzature_previste: str = Form("0"),
    altri_costi_previsti: str = Form("0"),
    note: str | None = Form(None),
    timeframe: str = Form("month"),
    start_date: str | None = Form(None),
    end_date: str | None = Form(None),
    current_user: User = Depends(get_current_active_user_html),
    db: Session = Depends(get_db),
):
    _ensure_economics_manage(current_user)
    site = db.query(Site).options(joinedload(Site.economic_budget)).filter(Site.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="Cantiere non trovato")

    try:
        values = {
            "ricavo_previsto": _normalize_entry_amount(ricavo_previsto),
            "materiali_previsti": _normalize_entry_amount(materiali_previsti),
            "manodopera_prevista": _normalize_entry_amount(manodopera_prevista),
            "trasporti_previsti": _normalize_entry_amount(trasporti_previsti),
            "mezzi_previsti": _normalize_entry_amount(mezzi_previsti),
            "attrezzature_previste": _normalize_entry_amount(attrezzature_previste),
            "altri_costi_previsti": _normalize_entry_amount(altri_costi_previsti),
        }
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Dati budget non validi")

    budget = site.economic_budget
    if not budget:
        budget = SiteEconomicBudget(
            site_id=site_id,
            created_by_id=getattr(current_user, "id", None),
        )
        db.add(budget)

    for field_name, value in values.items():
        setattr(budget, field_name, value)
    budget.note = (note or "").strip() or None
    budget.updated_by_id = getattr(current_user, "id", None)
    db.commit()

    return RedirectResponse(
        url=f"/manager/cantieri/{site_id}/economics?timeframe={timeframe}&start_date={start_date or ''}&end_date={end_date or ''}",
        status_code=303,
    )


@router.post("/manager/cantieri/{site_id}/economics/budget/delete", name="manager_site_economics_budget_delete")
def manager_site_economics_budget_delete(
    site_id: int,
    timeframe: str = Form("month"),
    start_date: str | None = Form(None),
    end_date: str | None = Form(None),
    current_user: User = Depends(get_current_active_user_html),
    db: Session = Depends(get_db),
):
    _ensure_economics_manage(current_user)
    budget = db.query(SiteEconomicBudget).filter(SiteEconomicBudget.site_id == site_id).first()
    if not budget:
        raise HTTPException(status_code=404, detail="Budget non trovato")
    db.delete(budget)
    db.commit()
    return RedirectResponse(
        url=f"/manager/cantieri/{site_id}/economics?timeframe={timeframe}&start_date={start_date or ''}&end_date={end_date or ''}",
        status_code=303,
    )


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
        if not can_view_site_margin(current_user) and parsed_type == SiteEconomicEntryTypeEnum.revenue:
            raise HTTPException(status_code=403, detail="Solo admin possono registrare ricavi")
    except HTTPException:
        raise
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
        if not can_view_site_margin(current_user) and parsed_type == SiteEconomicEntryTypeEnum.revenue:
            raise HTTPException(status_code=403, detail="Solo admin possono registrare ricavi")
    except HTTPException:
        raise
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


@router.post("/manager/cantieri/{site_id}/economics/auto-cost-config", name="manager_site_economics_auto_cost_config")
@router.patch("/manager/cantieri/{site_id}/economics/auto-cost-config")
def manager_site_economics_auto_cost_config(
    site_id: int,
    costo_manodopera_persona_giorno: str = Form("0"),
    costo_cemento_mc: str = Form("0"),
    costo_ferro_ton: str = Form("0"),
    costo_ferro_kg: str = Form("0"),
    altri_prezzi_json: str = Form("{}"),
    manual_material_entries_override_auto: str | None = Form(None),
    timeframe: str = Form("month"),
    start_date: str | None = Form(None),
    end_date: str | None = Form(None),
    current_user: User = Depends(get_current_active_user_html),
    db: Session = Depends(get_db),
):
    _ensure_economics_manage(current_user)
    site = db.query(Site).options(joinedload(Site.economic_auto_params)).filter(Site.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="Cantiere non trovato")

    try:
        parsed_labor = _normalize_entry_amount(costo_manodopera_persona_giorno)
        parsed_cemento = _normalize_entry_amount(costo_cemento_mc)
        parsed_ferro_ton = _normalize_entry_amount(costo_ferro_ton)
        parsed_ferro_kg = _normalize_entry_amount(costo_ferro_kg)
        parsed_altri_prezzi = _parse_material_prices(altri_prezzi_json)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Configurazione prezzi non valida")

    params = site.economic_auto_params
    if params is None:
        params = SiteEconomicAutoParams(site_id=site.id, created_by_id=getattr(current_user, "id", None))
        db.add(params)
    params.costo_manodopera_persona_giorno = parsed_labor
    params.costo_cemento_mc = parsed_cemento
    params.costo_ferro_ton = parsed_ferro_ton
    params.costo_ferro_kg = parsed_ferro_kg
    params.altri_prezzi_json = _serialize_material_prices(parsed_altri_prezzi)
    params.manual_material_entries_override_auto = manual_material_entries_override_auto in {"1", "true", "True", "on", "yes"}
    params.updated_by_id = getattr(current_user, "id", None)
    db.commit()

    return RedirectResponse(
        url=f"/manager/cantieri/{site_id}/economics?timeframe={timeframe}&start_date={start_date or ''}&end_date={end_date or ''}",
        status_code=303,
    )


@router.get("/manager/cantieri/{site_id}/economics/auto-cost-config", name="manager_site_economics_auto_cost_config_get")
def manager_site_economics_auto_cost_config_get(
    site_id: int,
    current_user: User = Depends(get_current_active_user_html),
    db: Session = Depends(get_db),
):
    _ensure_economics_access(current_user)
    site = (
        db.query(Site)
        .options(
            joinedload(Site.economic_auto_params).joinedload(SiteEconomicAutoParams.created_by),
            joinedload(Site.economic_auto_params).joinedload(SiteEconomicAutoParams.updated_by),
        )
        .filter(Site.id == site_id)
        .first()
    )
    if not site:
        raise HTTPException(status_code=404, detail="Cantiere non trovato")

    return {
        "site_id": site.id,
        "params": _serialize_auto_params(site.economic_auto_params),
    }
