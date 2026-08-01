"""AI service demo mode + Gemini failure behaviour."""
import asyncio

import pytest

import ai_service


def test_demo_mode_is_active_without_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    assert ai_service.is_demo_mode() is True


def test_demo_title_cleans_and_preserves_codes(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    title = asyncio.run(ai_service.improve_title("apple airpods pro 2 kablosuz kulaklık!!!", "Elektronik"))
    assert "!!!" not in title
    assert "Airpods" in title or "AIRPODS" in title
    assert "2" in title  # numeric model preserved


def test_demo_description_never_invents_specs(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    desc = asyncio.run(ai_service.improve_description(
        "SAMSUNG Galaxy A55 128GB Akıllı Telefon Siyah",
        "Elektronik",
        None,
    ))
    # Demo output should be conservative — no fabricated "daily use" style claim
    assert "günlük kullanıma uygun" not in desc.lower()
    # But must preserve codes/dimensions from the source
    assert "128GB" in desc or "A55" in desc


def test_gemini_failure_surfaces_error(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "bogus-key")

    def boom(prompt):
        raise ai_service.AIProviderError("network down")

    monkeypatch.setattr(ai_service, "_gemini_call", boom)
    with pytest.raises(ai_service.AIProviderError):
        asyncio.run(ai_service.improve_title("Test", "Cat"))
