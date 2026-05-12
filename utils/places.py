from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy.orm import Session

from models import Depot, Site

LocationKind = Literal["site", "depot"]
DEFAULT_DEPOT_NAMES = {"montauroux", "st. jeannet", "st jeannet", "sommariva", "cantieri"}


@dataclass(frozen=True)
class SelectablePlace:
    kind: LocationKind
    id: int
    name: str
    city: str | None
    address: str | None
    is_active: bool
    lat: float | None
    lng: float | None

    @property
    def value(self) -> str:
        return f"{self.kind}:{self.id}"

    @property
    def kind_label(self) -> str:
        return "Cantiere" if self.kind == "site" else "Deposito"

    @property
    def label(self) -> str:
        return format_place_label(self.kind, self.name)


def format_place_label(kind: str | None, name: str | None) -> str:
    cleaned_name = (name or "").strip()
    if not cleaned_name:
        return "—"
    if kind == "site":
        return f"[Cantiere] {cleaned_name}"
    if kind == "depot":
        return f"[Deposito] {cleaned_name}"
    return cleaned_name


def parse_place_value(raw_value: str | None) -> tuple[LocationKind | None, int | None]:
    raw = (raw_value or "").strip()
    if not raw or ":" not in raw:
        return None, None
    kind_raw, id_raw = raw.split(":", 1)
    if kind_raw not in ("site", "depot"):
        return None, None
    if not id_raw.isdigit():
        return None, None
    return kind_raw, int(id_raw)


def get_selectable_places(
    db: Session,
    *,
    include_inactive: bool = False,
) -> list[SelectablePlace]:
    site_query = db.query(Site)
    depot_query = db.query(Depot)
    if not include_inactive:
        site_query = site_query.filter(Site.is_active.is_(True))
        depot_query = depot_query.filter(Depot.is_active.is_(True))

    sites = site_query.order_by(Site.name.asc()).all()
    depots = [
        depot
        for depot in depot_query.order_by(Depot.name.asc()).all()
        if (depot.name or "").strip().lower() not in DEFAULT_DEPOT_NAMES
    ]

    places = [
        SelectablePlace(
            kind="site",
            id=site.id,
            name=site.name,
            city=site.city,
            address=site.address,
            is_active=bool(site.is_active),
            lat=site.lat,
            lng=site.lng,
        )
        for site in sites
    ]
    places.extend(
        SelectablePlace(
            kind="depot",
            id=depot.id,
            name=depot.name,
            city=depot.city,
            address=depot.address,
            is_active=bool(depot.is_active),
            lat=depot.lat,
            lng=depot.lng,
        )
        for depot in depots
    )
    return sorted(places, key=lambda place: (place.name or "").lower())


def get_place_by_value(
    db: Session,
    raw_value: str | None,
    *,
    include_inactive: bool = True,
) -> SelectablePlace | None:
    kind, record_id = parse_place_value(raw_value)
    if not kind or record_id is None:
        return None

    if kind == "site":
        record = db.query(Site).filter(Site.id == record_id).first()
        if not record or (not include_inactive and not record.is_active):
            return None
        return SelectablePlace(
            kind="site",
            id=record.id,
            name=record.name,
            city=record.city,
            address=record.address,
            is_active=bool(record.is_active),
            lat=record.lat,
            lng=record.lng,
        )

    record = db.query(Depot).filter(Depot.id == record_id).first()
    if not record or (not include_inactive and not record.is_active):
        return None
    if (record.name or "").strip().lower() in DEFAULT_DEPOT_NAMES:
        return None
    return SelectablePlace(
        kind="depot",
        id=record.id,
        name=record.name,
        city=record.city,
        address=record.address,
        is_active=bool(record.is_active),
        lat=record.lat,
        lng=record.lng,
    )
