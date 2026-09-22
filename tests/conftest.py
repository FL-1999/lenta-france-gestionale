"""Always isolate the test suite from configured application/production databases."""
import os
import tempfile
from pathlib import Path

_test_directory = tempfile.TemporaryDirectory(prefix="lenta-tests-")
os.environ["DATABASE_URL"] = "sqlite:///" + (Path(_test_directory.name) / "test.db").as_posix()
os.environ["SECRET_KEY"] = "isolated-tests-only-not-for-deployment"
os.environ["APP_ENV"] = "test"
os.environ.pop("ADMIN_EMAIL", None)
os.environ.pop("ADMIN_PASSWORD", None)
for _key in list(os.environ):
    if _key.startswith("SHAREPOINT_") or _key == "CLOUD_ARCHIVE_OWNER_EMAIL":
        os.environ.pop(_key, None)


def pytest_sessionfinish(session, exitstatus):
    from database import engine

    engine.dispose()
    _test_directory.cleanup()
