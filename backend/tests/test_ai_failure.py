"""Verify /api/products/{id}/improve returns HTTP 502 with Turkish message when
Gemini SDK raises. Uses TestClient with monkeypatched _gemini_call."""
import os
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))


def test_gemini_failure_returns_502(tmp_db, client, monkeypatch):
    # Force non-demo mode
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-value")
    import ai_service
    def _raise(*a, **kw):
        raise ai_service.AIProviderError("boom")
    monkeypatch.setattr(ai_service, "_gemini_call", _raise)
    # Also monkeypatch demo_mode check
    monkeypatch.setattr(ai_service, "is_demo_mode", lambda: False)

    # Seed a product
    from database import SessionLocal
    from models import Product
    db = SessionLocal()
    p = Product(sku="GEM_TEST_1", name="Test Ürün", stock=0)
    db.add(p); db.commit(); db.refresh(p)
    pid = p.id
    db.close()

    r = client.post(f"/api/products/{pid}/improve", json={"kind": "both"})
    assert r.status_code == 502, r.text
    assert "AI" in r.text or "sağlayıcı" in r.text.lower()
