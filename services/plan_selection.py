"""One definition of the drawing opened by default in a site's plan editor."""
from datetime import datetime


def current_plan(rows):
    active = [row for row in rows if row.removed_at is None]
    confirmed = [row for row in active if row.approved]
    return max(confirmed, key=lambda row: (row.approved_at or datetime.min, row.id),
               default=max(active, key=lambda row: row.id, default=None))
