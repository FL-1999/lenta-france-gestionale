from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Iterable

REVENUE_ENTRY_TYPE = "revenue"
LABOR_CATEGORY = "manodopera"


def is_weekend_day(value: date) -> bool:
    return value.weekday() >= 5


def parse_iso_date(raw: str | None, fallback: date) -> date:
    if not raw:
        return fallback
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return fallback


def week_bounds(anchor: date) -> tuple[date, date]:
    start = anchor - timedelta(days=anchor.weekday())
    return start, start + timedelta(days=6)


def month_bounds(anchor: date) -> tuple[date, date]:
    start = anchor.replace(day=1)
    next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return start, next_month - timedelta(days=1)


def resolve_period(
    timeframe: str,
    start_raw: str | None,
    end_raw: str | None,
    reference: date | None = None,
) -> tuple[date, date, str]:
    timeframe = timeframe if timeframe in {"day", "week", "month", "custom"} else "month"
    today = reference or date.today()

    if timeframe == "day":
        start = end = parse_iso_date(start_raw or end_raw, today)
    elif timeframe == "week":
        start, end = week_bounds(parse_iso_date(start_raw or end_raw, today))
    elif timeframe == "month":
        start, end = month_bounds(parse_iso_date(start_raw or end_raw, today))
    else:
        start = parse_iso_date(start_raw, today.replace(day=1))
        end = parse_iso_date(end_raw, today)
        if start > end:
            start, end = end, start

    return start, end, timeframe


def serialize_timeframe_filters(start_date: date, end_date: date, timeframe: str) -> dict[str, str]:
    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "timeframe": timeframe,
    }


def compute_labor_flags(work_date: date, is_active: bool | None = None) -> tuple[bool, bool]:
    weekend = is_weekend_day(work_date)
    if not weekend:
        return False, True
    return True, bool(is_active)


def compute_labor_total(worker_count: int, unit_cost: float, is_active: bool) -> float:
    if not is_active:
        return 0.0
    return round(float(worker_count or 0) * float(unit_cost or 0.0), 2)


def _entry_category_value(category: Any) -> str:
    return category.value if hasattr(category, "value") else str(category)


def _entry_type_value(entry_type: Any) -> str:
    return entry_type.value if hasattr(entry_type, "value") else str(entry_type)


def _amount(value: Any) -> float:
    return round(float(value or 0.0), 2)


def _active_labor_in_range(labor_entries: Iterable[Any], start_date: date, end_date: date) -> list[Any]:
    return [
        entry
        for entry in labor_entries
        if start_date <= entry.work_date <= end_date and bool(entry.is_active)
    ]


def calculate_labor_totals(labor_entries: Iterable[Any], start_date: date, end_date: date) -> dict[str, float]:
    total = 0.0
    for entry in _active_labor_in_range(labor_entries, start_date, end_date):
        total += _amount(getattr(entry, "total_cost", 0))
    return {"total": round(total, 2)}


def calculate_daily_totals(
    economic_entries: Iterable[Any],
    labor_entries: Iterable[Any],
    target_date: date,
) -> dict[str, float]:
    return calculate_period_totals(economic_entries, labor_entries, target_date, target_date)


def calculate_weekly_totals(
    economic_entries: Iterable[Any],
    labor_entries: Iterable[Any],
    anchor: date,
) -> dict[str, float]:
    start, end = week_bounds(anchor)
    return calculate_period_totals(economic_entries, labor_entries, start, end)


def calculate_monthly_totals(
    economic_entries: Iterable[Any],
    labor_entries: Iterable[Any],
    anchor: date,
) -> dict[str, float]:
    start, end = month_bounds(anchor)
    return calculate_period_totals(economic_entries, labor_entries, start, end)


def calculate_period_totals(
    economic_entries: Iterable[Any],
    labor_entries: Iterable[Any],
    start_date: date,
    end_date: date,
) -> dict[str, float]:
    revenues = 0.0
    costs = 0.0

    for entry in economic_entries:
        if not (start_date <= entry.entry_date <= end_date):
            continue
        amount = _amount(getattr(entry, "amount", 0))
        if _entry_type_value(getattr(entry, "entry_type", "")) == REVENUE_ENTRY_TYPE:
            revenues += amount
        else:
            costs += amount

    labor_costs = calculate_labor_totals(labor_entries, start_date, end_date)["total"]
    costs += labor_costs

    margin = revenues - costs
    return {
        "ricavi": round(revenues, 2),
        "costi": round(costs, 2),
        "costo_manodopera": round(labor_costs, 2),
        "margine": round(margin, 2),
        "utile_perdita": round(margin, 2),
    }


def build_daily_trend_series(
    economic_entries: Iterable[Any],
    labor_entries: Iterable[Any],
    start_date: date,
    end_date: date,
) -> list[dict[str, float | str]]:
    buckets: dict[date, dict[str, float | str]] = {}
    current = start_date
    while current <= end_date:
        buckets[current] = {
            "data": current.isoformat(),
            "costi": 0.0,
            "ricavi": 0.0,
            "margine": 0.0,
        }
        current += timedelta(days=1)

    for entry in economic_entries:
        if not (start_date <= entry.entry_date <= end_date):
            continue
        bucket = buckets.setdefault(
            entry.entry_date,
            {"data": entry.entry_date.isoformat(), "costi": 0.0, "ricavi": 0.0, "margine": 0.0},
        )
        amount = _amount(getattr(entry, "amount", 0))
        if _entry_type_value(getattr(entry, "entry_type", "")) == REVENUE_ENTRY_TYPE:
            bucket["ricavi"] = round(float(bucket["ricavi"]) + amount, 2)
        else:
            bucket["costi"] = round(float(bucket["costi"]) + amount, 2)

    for entry in labor_entries:
        if not bool(entry.is_active) or not (start_date <= entry.work_date <= end_date):
            continue
        bucket = buckets.setdefault(
            entry.work_date,
            {"data": entry.work_date.isoformat(), "costi": 0.0, "ricavi": 0.0, "margine": 0.0},
        )
        bucket["costi"] = round(float(bucket["costi"]) + _amount(getattr(entry, "total_cost", 0)), 2)

    rows = []
    for day in sorted(buckets):
        bucket = buckets[day]
        bucket["margine"] = round(float(bucket["ricavi"]) - float(bucket["costi"]), 2)
        rows.append(bucket)
    return rows


def build_category_totals(
    economic_entries: Iterable[Any],
    labor_entries: Iterable[Any],
    start_date: date,
    end_date: date,
) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for entry in economic_entries:
        if not (start_date <= entry.entry_date <= end_date):
            continue
        if _entry_type_value(entry.entry_type) == REVENUE_ENTRY_TYPE:
            continue
        totals[_entry_category_value(entry.category)] += _amount(entry.amount)

    totals[LABOR_CATEGORY] += calculate_labor_totals(labor_entries, start_date, end_date)["total"]
    return {key: round(value, 2) for key, value in totals.items()}
