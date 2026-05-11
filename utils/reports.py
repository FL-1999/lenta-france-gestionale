from __future__ import annotations

from typing import Iterable

_TOLERANCE = 0.01


def _as_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def report_man_hours(report: object) -> float:
    """Return the total man-hours for a report from nominative worker rows."""
    workers: Iterable[object] = getattr(report, "workers", None) or []
    total = sum(_as_float(getattr(worker, "hours_worked", 0.0)) for worker in workers)
    if total > 0:
        return total

    total_hours = _as_float(getattr(report, "total_hours", 0.0))
    workers_count = int(_as_float(getattr(report, "workers_count", 0), 0.0))
    return total_hours * workers_count if workers_count > 1 else total_hours


def report_total_hours(report: object) -> float:
    """
    Return the report workday duration to display as "Ore totali".

    Older reports may have stored total_hours as the sum of each worker's hours
    (for example 8h x 2 workers = 16h). In that legacy case, derive the workday
    duration from the longest worker row instead of showing man-hours.
    """
    stored_total = _as_float(getattr(report, "total_hours", 0.0))
    workers = list(getattr(report, "workers", None) or [])
    if not workers:
        return stored_total

    worker_hours = [
        _as_float(getattr(worker, "hours_worked", 0.0)) for worker in workers
    ]
    positive_hours = [hours for hours in worker_hours if hours > 0]
    if not positive_hours:
        return stored_total

    man_hours = sum(worker_hours)
    if len(worker_hours) > 1 and abs(stored_total - man_hours) <= _TOLERANCE:
        return max(positive_hours)

    return stored_total
