"""Shared test fixtures. Every test uses a fresh, temporary SQLite DB.

Tests create schema directly with Base.metadata.create_all against the
temporary database — this is explicitly allowed by the Phase 1 policy
("May only be used explicitly in isolated automated tests with temporary
databases"). In production and normal application startup, Alembic is the
sole schema migration mechanism.
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture()
def tmp_db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setenv("SQLITE_PATH", path)
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("DISABLE_SAMPLE_SEED", "1")
    monkeypatch.setenv("DISABLE_MIGRATIONS", "1")

    # Reload modules so they pick up the new SQLITE_PATH.
    for mod in [
        "server", "merchant_routes", "merchant_service",
        "quality_service", "revision_service",
        "sample_data", "ai_service", "models", "database",
    ]:
        if mod in sys.modules:
            del sys.modules[mod]

    import database  # noqa: F401
    import models  # noqa: F401
    import server as server_mod

    # Invariant: production goes through Alembic. Tests MUST opt out.
    assert os.environ.get("DISABLE_MIGRATIONS") == "1", \
        "Tests must set DISABLE_MIGRATIONS=1 and create schema via Base.metadata.create_all"

    # Create schema on the temporary database. Production uses Alembic.
    database.Base.metadata.create_all(bind=database.engine)

    yield server_mod

    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture()
def client(tmp_db):
    from fastapi.testclient import TestClient
    with TestClient(tmp_db.app) as c:
        yield c
