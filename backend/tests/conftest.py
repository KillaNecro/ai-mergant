"""Shared test fixtures. Every test uses a fresh, temporary SQLite DB."""
import os
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture()
def tmp_db(monkeypatch):
    """Point the app at a temporary SQLite file for the duration of the test."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setenv("SQLITE_PATH", path)
    monkeypatch.setenv("GEMINI_API_KEY", "")  # force demo mode by default
    monkeypatch.setenv("DISABLE_SAMPLE_SEED", "1")

    # Reload database + models + server so they pick up the new env var.
    for mod in [
        "server", "sample_data", "ai_service", "models", "database",
    ]:
        if mod in sys.modules:
            del sys.modules[mod]

    import database  # noqa: F401
    import models  # noqa: F401
    import server as server_mod  # noqa: E402
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
