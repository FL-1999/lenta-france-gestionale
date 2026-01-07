from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from auth import get_current_active_user_html
from database import get_db
from models import (
    Fiche,
    FicheTypeEnum,
    Machine,
    Report,
    RoleEnum,
    Site,
    User,
)
from permissions import has_perm
from template_context import render_template, register_manager_badges


router = APIRouter(tags=["manager-reports"])
templates = Jinja2Templates(directory="templates")
register_manager_badges(templates)

REPORT_TYPES = {
    "cantieri": "Cantieri",
    "caposquadra": "Caposquadra",
    "mezzi": "Mezzi",
}

PRESET_OPTIONS = {
    "last_2_weeks": "Ultime 2 settimane",
    "current_month": "Mese corrente",
}


def _ensure_manager(user: User) -> None:
    if not has_perm(user, "manager.access"):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _resolve_period(
    date_from: date | None,
    date_to: date | None,
    preset: str | None,
) -> tuple[date, date, str]:
    today = date.today()
    if preset == "last_2_weeks" and not (date_from or date_to):
        start = today - timedelta(days=13)
        return start, today, preset
    if preset == "current_month" and not (date_from or date_to):
        start = today.replace(day=1)
        next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        end = next_month - timedelta(days=1)
        return start, end, preset

    if date_from and date_to:
        start, end = date_from, date_to
    elif date_from:
        start, end = date_from, today
    elif date_to:
        start, end = date_to, date_to
    else:
        start = today.replace(day=1)
        next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        end = next_month - timedelta(days=1)
    if start > end:
        start, end = end, start
    active_preset = preset if preset in PRESET_OPTIONS and not (date_from or date_to) else ""
    return start, end, active_preset


def _serialize_date(value: date | None) -> str:
    return value.isoformat() if value else ""


def _build_cantieri_report(
    db: Session,
    start_date: date,
    end_date: date,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    report_rows = (
        db.query(
            Site.id.label("site_id"),
            Site.name.label("site_name"),
            Site.code.label("site_code"),
            Site.status.label("site_status"),
            func.coalesce(func.sum(Report.total_hours), 0).label("total_hours"),
            func.count(Report.id).label("reports_count"),
        )
        .outerjoin(
            Report,
            (Report.site_id == Site.id)
            & (Report.date >= start_date)
            & (Report.date <= end_date),
        )
        .filter(Site.is_active.is_(True))
        .group_by(Site.id)
        .order_by(Site.name.asc())
        .all()
    )

    rows = [
        {
            "site_id": row.site_id,
            "site_name": row.site_name,
            "site_code": row.site_code,
            "site_status": row.site_status.value if row.site_status else "-",
            "total_hours": float(row.total_hours or 0),
            "reports_count": int(row.reports_count or 0),
        }
        for row in report_rows
    ]

    chart_data = [
        {"label": row["site_name"], "value": row["total_hours"]} for row in rows
    ]
    return rows, chart_data


def _build_caposquadra_report(
    db: Session,
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    capi = (
        db.query(User)
        .filter(User.role == RoleEnum.caposquadra)
        .order_by(User.full_name.asc(), User.email.asc())
        .all()
    )

    site_counts = dict(
        db.query(
            Site.caposquadra_id,
            func.count(Site.id),
        )
        .filter(Site.is_active.is_(True), Site.caposquadra_id.isnot(None))
        .group_by(Site.caposquadra_id)
        .all()
    )

    report_stats = {
        row.created_by_id: {
            "reports_count": int(row.reports_count or 0),
            "total_hours": float(row.total_hours or 0),
        }
        for row in db.query(
            Report.created_by_id,
            func.count(Report.id).label("reports_count"),
            func.coalesce(func.sum(Report.total_hours), 0).label("total_hours"),
        )
        .filter(Report.date >= start_date, Report.date <= end_date)
        .group_by(Report.created_by_id)
        .all()
    }

    rows = []
    for capo in capi:
        stats = report_stats.get(capo.id, {"reports_count": 0, "total_hours": 0.0})
        rows.append(
            {
                "capo_id": capo.id,
                "capo_name": capo.full_name or capo.email,
                "active_sites": int(site_counts.get(capo.id, 0) or 0),
                "total_hours": float(stats["total_hours"]),
                "reports_count": int(stats["reports_count"]),
            }
        )
    return rows


def _build_mezzi_report(
    db: Session,
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    machines = (
        db.query(Machine)
        .filter(Machine.is_active.is_(True))
        .order_by(Machine.name.asc())
        .all()
    )

    downtime_case = case(
        (
            Fiche.fiche_type.in_(
                [FicheTypeEnum.fermo_macchina, FicheTypeEnum.controllo]
            ),
            1,
        ),
        else_=0,
    )

    usage_stats = {
        row.machine_id: {
            "usage_days": int(row.usage_days or 0),
            "downtime_count": int(row.downtime_count or 0),
        }
        for row in db.query(
            Fiche.machine_id,
            func.count(func.distinct(Fiche.date)).label("usage_days"),
            func.coalesce(func.sum(downtime_case), 0).label("downtime_count"),
        )
        .filter(
            Fiche.machine_id.isnot(None),
            Fiche.date >= start_date,
            Fiche.date <= end_date,
        )
        .group_by(Fiche.machine_id)
        .all()
    }

    rows = []
    for machine in machines:
        stats = usage_stats.get(
            machine.id,
            {"usage_days": 0, "downtime_count": 0},
        )
        rows.append(
            {
                "machine_id": machine.id,
                "machine_name": machine.name,
                "machine_code": machine.code or "-",
                "machine_status": machine.status or "-",
                "usage_days": int(stats["usage_days"]),
                "downtime_count": int(stats["downtime_count"]),
            }
        )
    return rows


def _export_csv(filename: str, rows: list[dict[str, Any]], headers: list[str]) -> Response:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers)
    for row in rows:
        writer.writerow([row.get(header, "") for header in headers])
    content = buffer.getvalue()
    buffer.close()
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/manager/report",
    response_class=HTMLResponse,
    name="manager_reports_dashboard",
)
def manager_reports_dashboard(
    request: Request,
    report_type: str = "cantieri",
    date_from: str | None = None,
    date_to: str | None = None,
    preset: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)

    report_type = report_type if report_type in REPORT_TYPES else "cantieri"
    parsed_from = _parse_date(date_from)
    parsed_to = _parse_date(date_to)
    start_date, end_date, active_preset = _resolve_period(
        parsed_from, parsed_to, preset
    )

    rows: list[dict[str, Any]]
    chart_data: list[dict[str, Any]] = []
    if report_type == "cantieri":
        rows, chart_data = _build_cantieri_report(db, start_date, end_date)
    elif report_type == "caposquadra":
        rows = _build_caposquadra_report(db, start_date, end_date)
    else:
        rows = _build_mezzi_report(db, start_date, end_date)

    return render_template(
        templates,
        request,
        "manager/reportistica.html",
        {
            "report_type": report_type,
            "report_label": REPORT_TYPES[report_type],
            "report_types": REPORT_TYPES,
            "preset_options": PRESET_OPTIONS,
            "filters": {
                "date_from": _serialize_date(start_date),
                "date_to": _serialize_date(end_date),
                "preset": active_preset,
                "report_type": report_type,
            },
            "rows": rows,
            "chart_data": chart_data,
        },
        db,
        current_user,
    )


@router.get(
    "/manager/report/export",
    response_class=Response,
    name="manager_reports_export",
)
def manager_reports_export(
    report_type: str = "cantieri",
    date_from: str | None = None,
    date_to: str | None = None,
    preset: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)

    report_type = report_type if report_type in REPORT_TYPES else "cantieri"
    parsed_from = _parse_date(date_from)
    parsed_to = _parse_date(date_to)
    start_date, end_date, _ = _resolve_period(parsed_from, parsed_to, preset)

    if report_type == "cantieri":
        rows, _ = _build_cantieri_report(db, start_date, end_date)
        headers = ["site_name", "site_code", "site_status", "total_hours", "reports_count"]
        filename = f"report_cantieri_{start_date:%Y%m%d}_{end_date:%Y%m%d}.csv"
    elif report_type == "caposquadra":
        rows = _build_caposquadra_report(db, start_date, end_date)
        headers = ["capo_name", "active_sites", "total_hours", "reports_count"]
        filename = f"report_caposquadra_{start_date:%Y%m%d}_{end_date:%Y%m%d}.csv"
    else:
        rows = _build_mezzi_report(db, start_date, end_date)
        headers = [
            "machine_name",
            "machine_code",
            "machine_status",
            "usage_days",
            "downtime_count",
        ]
        filename = f"report_mezzi_{start_date:%Y%m%d}_{end_date:%Y%m%d}.csv"

    return _export_csv(filename, rows, headers)
