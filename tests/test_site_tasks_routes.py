import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from auth import get_current_active_user_html
from database import Base, SessionLocal, engine
from main import app
from models import RoleEnum, Site, SiteTask, SiteTaskPriorityEnum, SiteTaskStatusEnum, User


class SiteTasksRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        self.client = TestClient(app, raise_server_exceptions=True)
        self.unique = uuid4().hex

    def tearDown(self) -> None:
        app.dependency_overrides = {}

    def _create_manager_and_site(self) -> tuple[int, int]:
        session = SessionLocal()
        try:
            manager = User(
                email=f"manager-site-task-{self.unique}@example.com",
                full_name="Manager Site Task",
                hashed_password="x",
                role=RoleEnum.manager,
                is_active=True,
            )
            site = Site(
                name=f"Cantiere Task {self.unique}",
                code=f"TASK-{self.unique[:8]}",
                is_active=True,
            )
            session.add_all([manager, site])
            session.commit()
            session.refresh(manager)
            session.refresh(site)
            return manager.id, site.id
        finally:
            session.close()

    def test_complete_task_sets_completion_metadata(self) -> None:
        manager_id, site_id = self._create_manager_and_site()

        session = SessionLocal()
        try:
            task = SiteTask(
                site_id=site_id,
                title="Task da completare",
                status=SiteTaskStatusEnum.da_fare,
                priority=SiteTaskPriorityEnum.media,
                created_by_id=manager_id,
                updated_by_id=manager_id,
                completed=False,
            )
            session.add(task)
            session.commit()
            session.refresh(task)
            task_id = task.id
        finally:
            session.close()

        app.dependency_overrides[get_current_active_user_html] = (
            lambda: SimpleNamespace(id=manager_id, role=RoleEnum.manager, full_name="Manager")
        )

        response = self.client.post(
            f"/manager/cantieri/{site_id}/tasks/{task_id}/complete",
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

        session = SessionLocal()
        try:
            completed_task = session.query(SiteTask).filter(SiteTask.id == task_id).first()
            self.assertIsNotNone(completed_task)
            self.assertTrue(completed_task.completed)
            self.assertEqual(completed_task.status, SiteTaskStatusEnum.completato)
            self.assertEqual(completed_task.completed_by_id, manager_id)
            self.assertIsNotNone(completed_task.completed_at)
        finally:
            session.close()

    def test_overview_shows_only_last_five_completed_tasks(self) -> None:
        manager_id, site_id = self._create_manager_and_site()

        session = SessionLocal()
        try:
            base_time = datetime(2026, 1, 1, 12, 0, 0)
            tasks: list[SiteTask] = []
            for index in range(6):
                tasks.append(
                    SiteTask(
                        site_id=site_id,
                        title=f"storico-task-{index}",
                        status=SiteTaskStatusEnum.completato,
                        priority=SiteTaskPriorityEnum.media,
                        created_by_id=manager_id,
                        updated_by_id=manager_id,
                        completed=True,
                        completed_by_id=manager_id,
                        completed_at=base_time + timedelta(minutes=index),
                    )
                )
            session.add_all(tasks)
            session.commit()
        finally:
            session.close()

        app.dependency_overrides[get_current_active_user_html] = (
            lambda: SimpleNamespace(id=manager_id, role=RoleEnum.manager, full_name="Manager")
        )

        response = self.client.get("/manager/note-operative", cookies={"lang": "it"})
        self.assertEqual(response.status_code, 200)

        # Most recent 5 present
        for index in range(1, 6):
            self.assertIn(f"storico-task-{index}", response.text)

        # Oldest excluded from quick summary
        self.assertNotIn("storico-task-0", response.text)


if __name__ == "__main__":
    unittest.main()
