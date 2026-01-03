import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from auth import hash_password
from database import Base
from deps import get_site_for_user
from models import RoleEnum, Site, User


class CaposquadraSitePermissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        cls.SessionLocal = sessionmaker(
            autocommit=False, autoflush=False, bind=cls.engine
        )
        Base.metadata.create_all(bind=cls.engine)

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(bind=cls.engine)

    def setUp(self):
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

    def test_capo_cannot_access_unassigned_site_detail(self):
        db = self.SessionLocal()
        try:
            capo = User(
                email="capo@example.com",
                full_name="Capo Uno",
                hashed_password=hash_password("password"),
                role=RoleEnum.caposquadra,
                is_active=True,
            )
            other_capo = User(
                email="capo2@example.com",
                full_name="Capo Due",
                hashed_password=hash_password("password"),
                role=RoleEnum.caposquadra,
                is_active=True,
            )
            db.add_all([capo, other_capo])
            db.commit()
            db.refresh(capo)
            db.refresh(other_capo)

            site = Site(
                name="Cantiere Test",
                code="SITE-001",
                caposquadra_id=other_capo.id,
                is_active=True,
            )
            db.add(site)
            db.commit()
            db.refresh(site)
            with self.assertRaises(HTTPException) as context:
                get_site_for_user(db, site.id, capo)
            self.assertEqual(context.exception.status_code, 403)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
