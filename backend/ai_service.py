"""AI service abstraction.

- If GEMINI_API_KEY is set: uses the official google-genai SDK.
- Otherwise: deterministic Turkish Demo Mode.

If Gemini is configured but the request fails, the caller receives an
`AIProviderError` — we never silently fall back to Demo Mode when a key
is present, per Phase 1 requirements.
"""
from __future__ import annotations

import os
import re
from typing import Optional


class AIProviderError(RuntimeError):
    """Raised when Gemini is configured but a request fails."""


def is_demo_mode() -> bool:
    return not bool(os.environ.get("GEMINI_API_KEY", "").strip())


def gemini_model() -> str:
    return os.environ.get("GEMINI_MODEL", "gemini-2.0-flash").strip() or "gemini-2.0-flash"


# ---------------- Deterministic Demo Generator ---------------- #

_TR_STOPWORDS = {
    "ve", "ile", "için", "bir", "bu", "şu", "olan", "olarak",
    "en", "çok", "yeni", "orijinal", "kaliteli", "süper", "harika",
    "muhteşem", "inanılmaz", "acil", "fırsat", "kampanya", "indirim",
    "ücretsiz", "kargo", "stokta", "hediyeli",
}


def _clean_title(text: str) -> str:
    if not text:
        return ""
    s = re.sub(r"[\s\-_/]+", " ", text).strip()
    s = re.sub(r"[!?]{2,}", "", s)
    s = re.sub(r"[.]{2,}", "", s)
    tokens = s.split(" ")
    cleaned, seen = [], set()
    for tok in tokens:
        low = tok.lower().strip(",.;:")
        if not low:
            continue
        if re.search(r"\d", tok) and re.search(r"[A-Za-zĞÜŞİÖÇğüşıöç]", tok):
            key = tok.upper()
            if key not in seen:
                cleaned.append(tok.upper() if len(tok) <= 6 else tok)
                seen.add(key)
            continue
        if low in _TR_STOPWORDS or low in seen:
            continue
        seen.add(low)
        cleaned.append(tok)
    result = []
    for tok in cleaned:
        if re.search(r"\d", tok):
            result.append(tok)
        else:
            result.append(tok[:1].upper() + tok[1:].lower() if tok else tok)
    title = " ".join(result).strip()
    if len(title) > 90:
        title = title[:87].rstrip() + "..."
    return title


def _preserved_codes(*sources: Optional[str]) -> list[str]:
    """Extract model/measurement codes to preserve (never invent)."""
    preserved: list[str] = []
    seen: set[str] = set()
    for src in sources:
        if not src:
            continue
        for match in re.findall(r"\b[A-Za-z]*\d+[A-Za-z0-9\-]*\b", src):
            key = match.upper()
            if key not in seen:
                preserved.append(match)
                seen.add(key)
    return preserved[:6]


def _demo_description(name: str, category: Optional[str], original: Optional[str]) -> str:
    clean_name = _clean_title(name) or name
    cat = (category or "Ürün").strip()
    preserved = _preserved_codes(name, original)
    lines = [
        f"{clean_name}, {cat.lower()} kategorisinde yer alan bir üründür.",
        "",
        "Öne çıkan bilgiler:",
        f"- Kategori: {cat}",
    ]
    if preserved:
        lines.append(f"- Model / ölçü kodları: {', '.join(preserved)}")
    if original:
        lines.append(f"- Ürün notu: {original.strip()[:200]}")
    lines.append("")
    lines.append(
        "Bu açıklama yalnızca sağlanan ürün adı, kategori ve mevcut açıklamadan "
        "türetilmiştir. Teknik özellikler için lütfen ürün sayfasındaki resmi "
        "spesifikasyonları kontrol edin."
    )
    return "\n".join(lines)


# ---------------- Gemini Integration (google-genai) ---------------- #

_SYSTEM_INSTRUCTION = (
    "Sen bir Türkçe e-ticaret içerik uzmanısın. Ürün başlıklarını ve "
    "açıklamalarını profesyonel, kısa, SEO uyumlu şekilde iyileştir. "
    "ASLA teknik özellik uydurma. Marka adları, ölçüler, model numaraları, "
    "malzemeler ve ürün kodlarını olduğu gibi koru. Kaynakta belirtilmeyen "
    "iddialarda bulunma."
)


def _gemini_call(prompt: str) -> str:
    api_key = os.environ["GEMINI_API_KEY"]
    try:
        from google import genai  # type: ignore
    except ImportError as exc:  # pragma: no cover - install issue
        raise AIProviderError(f"google-genai paketi yüklü değil: {exc}") from exc
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=gemini_model(),
            contents=f"{_SYSTEM_INSTRUCTION}\n\n{prompt}",
        )
        text = getattr(response, "text", None)
        if not text:
            raise AIProviderError("Gemini boş yanıt döndürdü")
        return text.strip()
    except AIProviderError:
        raise
    except Exception as exc:  # pragma: no cover - network dependent
        raise AIProviderError(f"Gemini isteği başarısız: {exc}") from exc


# ---------------- Public API ---------------- #

async def improve_title(name: str, category: Optional[str] = None) -> str:
    if is_demo_mode():
        return _clean_title(name)
    prompt = (
        f"Aşağıdaki ürün başlığını daha profesyonel ve Türkçe olarak yeniden yaz. "
        f"Yalnızca iyileştirilmiş başlığı tek satır olarak döndür.\n\n"
        f"Kategori: {category or '-'}\nBaşlık: {name}"
    )
    out = _gemini_call(prompt)
    return out.splitlines()[0].strip().strip('"').strip("'")[:120] or _clean_title(name)


async def improve_description(
    name: str,
    category: Optional[str] = None,
    original: Optional[str] = None,
) -> str:
    if is_demo_mode():
        return _demo_description(name, category, original)
    prompt = (
        f"Aşağıdaki ürün için profesyonel Türkçe bir açıklama yaz. "
        f"3-5 cümle + kısa madde işaretli özellik listesi içersin. "
        f"Sadece verilenlere dayan; teknik özellik uydurma. Marka adları, "
        f"ölçüler, model numaraları ve ürün kodlarını olduğu gibi koru.\n\n"
        f"Ürün Adı: {name}\nKategori: {category or '-'}\n"
        f"Mevcut Açıklama: {original or '-'}"
    )
    return _gemini_call(prompt)
