"""AI service abstraction with Demo Mode fallback.

If GEMINI_API_KEY is set, uses Gemini via emergentintegrations.
Otherwise falls back to a deterministic Turkish demo generator that
cleans titles and produces a structured description without inventing
technical specifications.
"""
from __future__ import annotations
import os
import re
from typing import Optional


def is_demo_mode() -> bool:
    return not bool(os.environ.get("GEMINI_API_KEY", "").strip())


# ---------------- Deterministic Demo Generator ---------------- #

_TR_STOPWORDS = {
    "ve", "ile", "için", "bir", "bu", "şu", "olan", "olarak",
    "en", "çok", "yeni", "orijinal", "kaliteli", "süper", "harika",
    "muhteşem", "inanılmaz", "acil", "fırsat", "kampanya", "indirim",
    "ücretsiz", "kargo", "stokta", "hediyeli", "!!!", "!!", "!",
}


def _clean_title(text: str) -> str:
    if not text:
        return ""
    # Normalize whitespace and separators
    s = re.sub(r"[\s\-_/]+", " ", text).strip()
    # Remove excessive punctuation
    s = re.sub(r"[!?]{2,}", "", s)
    s = re.sub(r"[.]{2,}", "", s)
    # Split tokens preserving codes (letters+digits) and brand-like Capitalized words
    tokens = s.split(" ")
    cleaned = []
    seen = set()
    for tok in tokens:
        low = tok.lower().strip(",.;:")
        if not low:
            continue
        # Preserve alphanumeric codes (e.g., XR-500, 128GB, 45mm) as-is
        if re.search(r"\d", tok) and re.search(r"[A-Za-zĞÜŞİÖÇğüşıöç]", tok):
            key = tok.upper()
            if key not in seen:
                cleaned.append(tok.upper() if len(tok) <= 6 else tok)
                seen.add(key)
            continue
        if low in _TR_STOPWORDS:
            continue
        if low in seen:
            continue
        seen.add(low)
        cleaned.append(tok)
    # Title Case for regular words, keep codes as-is
    result = []
    for tok in cleaned:
        if re.search(r"\d", tok):
            result.append(tok)
        else:
            result.append(tok[:1].upper() + tok[1:].lower() if tok else tok)
    title = " ".join(result).strip()
    # Limit length
    if len(title) > 90:
        title = title[:87].rstrip() + "..."
    return title


def _demo_description(name: str, category: Optional[str], original: Optional[str]) -> str:
    clean_name = _clean_title(name) or name
    cat = (category or "Ürün").strip()
    # Extract preserved codes/dimensions from original text
    preserved = []
    src = f"{name} {original or ''}"
    for match in re.findall(r"\b[A-Za-z]*\d+[A-Za-z0-9\-]*\b", src):
        if match.upper() not in [p.upper() for p in preserved]:
            preserved.append(match)
    preserved = preserved[:4]

    lines = [
        f"{clean_name}, {cat.lower()} kategorisinde tercih edilebilecek bir üründür.",
        "",
        "Öne çıkan özellikler:",
        f"- Kategori: {cat}",
    ]
    if preserved:
        lines.append(f"- Model/Ölçü bilgileri: {', '.join(preserved)}")
    lines.append("- Günlük kullanıma uygun tasarım")
    lines.append("- Sade ve profesyonel görünüm")
    lines.append("")
    lines.append(
        "Bu açıklama, ürün adı ve kategori bilgilerinden türetilmiştir. "
        "Teknik özellikler için lütfen ürün sayfasındaki spesifikasyonları inceleyin."
    )
    return "\n".join(lines)


# ---------------- Gemini Integration ---------------- #

async def _gemini_generate(prompt: str) -> str:
    """Call Gemini via emergentintegrations if a key is present."""
    from emergentintegrations.llm.chat import LlmChat, UserMessage  # type: ignore
    key = os.environ["GEMINI_API_KEY"]
    chat = LlmChat(
        api_key=key,
        session_id="merchant-os-lite",
        system_message=(
            "Sen bir Türkçe e-ticaret içerik uzmanısın. Ürün başlıklarını ve "
            "açıklamalarını profesyonel, kısa ve SEO uyumlu şekilde iyileştir. "
            "Asla teknik özellik uydurma. Marka adları, ölçüler, model numaraları, "
            "malzemeler ve ürün kodlarını olduğu gibi koru."
        ),
    ).with_model("gemini", "gemini-2.0-flash")
    response = await chat.send_message(UserMessage(text=prompt))
    return (response or "").strip()


# ---------------- Public API ---------------- #

async def improve_title(name: str, category: Optional[str] = None) -> str:
    if is_demo_mode():
        return _clean_title(name)
    prompt = (
        f"Aşağıdaki ürün başlığını daha profesyonel ve Türkçe olarak yeniden yaz. "
        f"Sadece iyileştirilmiş başlığı döndür, ek açıklama ekleme.\n\n"
        f"Kategori: {category or '-'}\nBaşlık: {name}"
    )
    try:
        out = await _gemini_generate(prompt)
        # Keep first line only
        return out.splitlines()[0].strip().strip('"').strip("'")[:120] or _clean_title(name)
    except Exception:
        return _clean_title(name)


async def improve_description(
    name: str,
    category: Optional[str] = None,
    original: Optional[str] = None,
) -> str:
    if is_demo_mode():
        return _demo_description(name, category, original)
    prompt = (
        f"Aşağıdaki ürün için profesyonel bir Türkçe açıklama yaz. "
        f"3-5 cümle ve kısa bir madde işaretli özellik listesi içersin. "
        f"Teknik özellik uydurma; sadece verilenlere dayan.\n\n"
        f"Ürün Adı: {name}\nKategori: {category or '-'}\n"
        f"Mevcut Açıklama: {original or '-'}"
    )
    try:
        return await _gemini_generate(prompt) or _demo_description(name, category, original)
    except Exception:
        return _demo_description(name, category, original)
