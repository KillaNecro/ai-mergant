"""AI service: Demo Mode + Gemini via google-genai.

Phase 2 adds `generate_suggestion` producing a structured payload:
    { provider, model, suggested_name, suggested_description,
      suggested_category, suggested_seo_title, suggested_meta_description,
      suggested_tags: [str, ...] }

Never invents technical specs. Preserves brands/codes/measurements. On
Gemini failure the caller receives AIProviderError — no silent fallback.
"""
from __future__ import annotations

import json
import os
import re
from typing import Optional


class AIProviderError(RuntimeError):
    """Raised when Gemini is configured but a request fails."""


def is_demo_mode() -> bool:
    return not bool(os.environ.get("GEMINI_API_KEY", "").strip())


def gemini_model() -> str:
    return os.environ.get("GEMINI_MODEL", "gemini-2.0-flash").strip() or "gemini-2.0-flash"


# ---------------- Deterministic Demo ----------------
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


def _demo_tags(name: str, category: Optional[str]) -> list[str]:
    tokens: list[str] = []
    if category:
        tokens.append(category.strip().lower())
    for tok in re.findall(r"[A-Za-zĞÜŞİÖÇğüşıöç0-9]+", name or ""):
        low = tok.lower()
        if low in _TR_STOPWORDS or len(low) < 3:
            continue
        if low not in tokens:
            tokens.append(low)
        if len(tokens) >= 8:
            break
    return tokens


# ---------------- Gemini ----------------
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
    except ImportError as exc:  # pragma: no cover
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


# ---------------- Public single-field helpers ----------------
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


# ---------------- Suggestion (Phase 2) ----------------
def _demo_suggestion(
    name: str, description: Optional[str], category: Optional[str],
) -> dict:
    clean_name = _clean_title(name) or name
    desc = _demo_description(name, category, description)
    seo_title = clean_name[:60].rstrip()
    first_line = desc.split("\n", 1)[0].strip()
    meta = (first_line[:155]).rstrip() if first_line else clean_name[:155]
    tags = _demo_tags(name, category)
    return {
        "provider": "demo",
        "model": "deterministic-v1",
        "suggested_name": clean_name,
        "suggested_description": desc,
        "suggested_category": category or None,
        "suggested_seo_title": seo_title,
        "suggested_meta_description": meta,
        "suggested_tags": tags,
    }


def _extract_json(text: str) -> Optional[dict]:
    if not text:
        return None
    # Try direct parse; else find first {...} block
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        pass
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except (TypeError, ValueError):
        return None


async def generate_suggestion(
    *,
    name: str,
    description: Optional[str],
    category: Optional[str],
    image_url: Optional[str] = None,
    product_url: Optional[str] = None,
    price: Optional[float] = None,
    issue_codes: Optional[list[str]] = None,
) -> dict:
    """Return a structured suggestion payload.

    Demo Mode → conservative deterministic content.
    Gemini    → structured JSON via strict prompt; raises AIProviderError on failure.
    """
    if is_demo_mode():
        return _demo_suggestion(name, description, category)

    issues_hint = ""
    if issue_codes:
        issues_hint = "\nMevcut kalite sorunları: " + ", ".join(issue_codes)

    prompt = (
        "Aşağıdaki ürün için Türkçe bir e-ticaret önerisi hazırla. Yanıtı SADECE "
        "aşağıdaki alanları içeren geçerli bir JSON nesnesi olarak döndür. "
        "Ek açıklama, kod bloğu veya metin ekleme.\n"
        "Alanlar: suggested_name (string), suggested_description (string), "
        "suggested_category (string), suggested_seo_title (string, <=60 karakter), "
        "suggested_meta_description (string, <=155 karakter), "
        "suggested_tags (max 8 kelime, dize dizisi).\n\n"
        "KURALLAR:\n"
        "- Boyut, malzeme, model numarası, uyumluluk veya sertifika UYDURMA.\n"
        "- Marka, SKU, ürün kodu ve ölçüleri OLDUĞU GİBİ koru.\n"
        "- Kaynakta yer almayan pazarlama iddialarında bulunma.\n"
        "- Fiyat, stok veya orijinal veriyi değiştirmeye çalışma.\n\n"
        f"Ürün:\n- Adı: {name}\n- Kategori: {category or '-'}\n"
        f"- Fiyat: {price if price is not None else '-'}\n"
        f"- Görsel URL: {image_url or '-'}\n"
        f"- Ürün URL: {product_url or '-'}\n"
        f"- Mevcut açıklama: {description or '-'}"
        f"{issues_hint}"
    )
    raw = _gemini_call(prompt)
    data = _extract_json(raw)
    if not isinstance(data, dict):
        raise AIProviderError("Gemini yanıtı JSON olarak çözümlenemedi")

    def _s(v):
        return v.strip() if isinstance(v, str) else None

    tags = data.get("suggested_tags") or []
    if not isinstance(tags, list):
        tags = []
    tags = [str(t).strip() for t in tags if str(t).strip()][:8]

    return {
        "provider": "gemini",
        "model": gemini_model(),
        "suggested_name": _s(data.get("suggested_name")) or _clean_title(name),
        "suggested_description": _s(data.get("suggested_description")),
        "suggested_category": _s(data.get("suggested_category")) or category,
        "suggested_seo_title": (_s(data.get("suggested_seo_title")) or "")[:60] or None,
        "suggested_meta_description": (_s(data.get("suggested_meta_description")) or "")[:155] or None,
        "suggested_tags": tags,
    }
