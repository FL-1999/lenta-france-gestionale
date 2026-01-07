from __future__ import annotations

import random
import time
from datetime import date, timedelta
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, select

from auth import get_current_active_user_html
from database import Base, SessionLocal, engine
from main import app
from models import Machine, Personale, Report, RoleEnum, Site, SiteStatusEnum, User
from models.veicoli import Veicolo


def _ensure_tables() -> None:
    Base.metadata.create_all(bind=engine)
    SQLModel.metadata.create_all(bind=engine)


def _seed_sqlalchemy() -> None:
    db = SessionLocal()
    try:
        user = db.query(User).first()
        if not user:
            user = User(
                email="manager@example.com",
                full_name="Manager Performance",
                role=RoleEnum.manager,
                hashed_password="placeholder",
                is_active=True,
            )
            db.add(user)
            db.flush()

        if db.query(Site).count() < 120:
            for idx in range(120):
                db.add(
                    Site(
                        name=f"Cantiere {idx}",
                        code=f"S{idx:03d}",
                        city="Lyon",
                        country="France",
                        status=random.choice(list(SiteStatusEnum)),
                        is_active=True,
                        lat=45.7,
                        lng=4.8,
                        caposquadra_id=user.id,
                    )
                )

        if db.query(Machine).count() < 120:
            for idx in range(120):
                db.add(
                    Machine(
                        name=f"Macchinario {idx}",
                        code=f"M{idx:03d}",
                        status=random.choice(["attivo", "fuori_servizio", "manutenzione"]),
                    )
                )

        if db.query(Report).count() < 200:
            base_date = date.today()
            for idx in range(200):
                report_date = base_date - timedelta(days=idx % 40)
                db.add(
                    Report(
                        date=report_date,
                        site_name_or_code=f"S{idx % 120:03d}",
                        total_hours=float(idx % 9),
                        workers_count=3,
                        created_by_id=user.id,
                    )
                )

        db.commit()
    finally:
        db.close()


def _seed_sqlmodel() -> None:
    with Session(engine) as session:
        existing = session.exec(select(Personale)).first()
        if not existing:
            for idx in range(120):
                session.add(
                    Personale(
                        nome=f"Nome{idx}",
                        cognome=f"Cognome{idx}",
                        ruolo="Operaio",
                        telefono="000000000",
                        email=f"persona{idx}@example.com",
                        attivo=True,
                    )
                )

        existing_vehicle = session.exec(select(Veicolo)).first()
        if not existing_vehicle:
            for idx in range(120):
                session.add(
                    Veicolo(
                        marca="Renault",
                        modello=f"Model {idx}",
                        targa=f"AB{idx:03d}CD",
                        anno=2020,
                        km=10000 + idx,
                        carburante="Diesel",
                    )
                )
        session.commit()


def _override_user() -> None:
    app.dependency_overrides[get_current_active_user_html] = lambda: SimpleNamespace(
        id=1,
        role=RoleEnum.manager,
        is_magazzino_manager=False,
        is_active=True,
        full_name="Manager Performance",
    )


def _measure(client: TestClient, path: str, runs: int = 3) -> None:
    durations = []
    for _ in range(runs):
        start = time.perf_counter()
        response = client.get(path)
        elapsed = (time.perf_counter() - start) * 1000
        durations.append(elapsed)
        if response.status_code != 200:
            raise RuntimeError(f"Request failed {path}: {response.status_code}")
    avg = sum(durations) / len(durations)
    print(f"{path} avg_ms={avg:.2f} samples={','.join(f'{d:.2f}' for d in durations)}")


def main() -> None:
    _ensure_tables()
    _seed_sqlalchemy()
    _seed_sqlmodel()
    _override_user()

    client = TestClient(app)

    _measure(client, "/manager/dashboard", runs=5)
    _measure(client, "/manager/cantieri?page=1&per_page=50")
    _measure(client, "/manager/macchinari?page=1&per_page=50")
    _measure(client, "/manager/personale?page=1&per_page=50")
    _measure(client, "/manager/veicoli?page=1&per_page=50")


if __name__ == "__main__":
    main()
