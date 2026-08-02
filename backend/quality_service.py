"""Deterministic product quality analysis.

Single source of truth for issue codes, weights, severity, and score.
Never invents facts about a product; only inspects existing fields.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, List, Optional

from sqlalchemy.orm import Session

from models import Product, ProductIssue


# ---------------- Configuration ----------------
MIN_DESCRIPTION_LEN = 40
MIN_TITLE_LEN = 15
MAX_TITLE_LEN = 90
UPPERCASE_THRESHOLD = 0.6  # fraction of alphabetic chars that are uppercase
GENERIC_TITLE_TOKENS = {"urun", "product", "test", "yeni urun", "adsiz"}

SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_CRITICAL = "critical"


@dataclass(frozen=True)
class IssueDef:
    code: str
    field: Optional[str]
    severity: str
    weight: int
    message: str
    recommendation: str


ISSUE_CATALOG: dict[str, IssueDef] = {
    "MISSING_SKU": IssueDef(
        "MISSING_SKU", "sku", SEVERITY_CRITICAL, 25,
        "SKU eksik.", "Ürüne benzersiz bir SKU tanımlayın.",
    ),
    "MISSING_NAME": IssueDef(
        "MISSING_NAME", "name", SEVERITY_CRITICAL, 30,
        "Ürün adı eksik.", "Ürüne kısa ve açıklayıcı bir başlık ekleyin.",
    ),
    "MISSING_DESCRIPTION": IssueDef(
        "MISSING_DESCRIPTION", "description", SEVERITY_CRITICAL, 20,
        "Ürün açıklaması eksik.",
        "Ürünün özelliklerini ve kullanım amacını içeren bir açıklama ekleyin.",
    ),
    "SHORT_DESCRIPTION": IssueDef(
        "SHORT_DESCRIPTION", "description", SEVERITY_WARNING, 10,
        f"Açıklama {MIN_DESCRIPTION_LEN} karakterden kısa.",
        "Açıklamayı en az birkaç cümle olacak şekilde genişletin.",
    ),
    "MISSING_PRICE": IssueDef(
        "MISSING_PRICE", "price", SEVERITY_CRITICAL, 20,
        "Fiyat tanımlanmamış.", "Ürün için geçerli bir satış fiyatı ekleyin.",
    ),
    "INVALID_PRICE": IssueDef(
        "INVALID_PRICE", "price", SEVERITY_CRITICAL, 20,
        "Fiyat sıfır veya negatif.", "Fiyatı 0'dan büyük bir değere güncelleyin.",
    ),
    "MISSING_CATEGORY": IssueDef(
        "MISSING_CATEGORY", "category", SEVERITY_WARNING, 8,
        "Kategori atanmamış.", "Ürüne uygun bir kategori seçin.",
    ),
    "MISSING_IMAGE": IssueDef(
        "MISSING_IMAGE", "image_url", SEVERITY_WARNING, 10,
        "Görsel URL tanımlı değil.", "Ürün için yüksek çözünürlüklü bir görsel bağlantısı ekleyin.",
    ),
    "INVALID_IMAGE_URL": IssueDef(
        "INVALID_IMAGE_URL", "image_url", SEVERITY_WARNING, 5,
        "Görsel URL geçerli bir http/https bağlantısı değil.",
        "Görsel URL'sini http:// veya https:// ile başlayacak şekilde düzeltin.",
    ),
    "MISSING_PRODUCT_URL": IssueDef(
        "MISSING_PRODUCT_URL", "product_url", SEVERITY_INFO, 3,
        "Ürün sayfası bağlantısı yok.",
        "Ürünün mağazadaki bağlantısını ekleyerek dış kanallara referans verin.",
    ),
    "TITLE_TOO_SHORT": IssueDef(
        "TITLE_TOO_SHORT", "name", SEVERITY_WARNING, 8,
        f"Ürün başlığı {MIN_TITLE_LEN} karakterden kısa.",
        "Marka, model veya ürün özelliğini ekleyerek başlığı genişletin.",
    ),
    "TITLE_TOO_LONG": IssueDef(
        "TITLE_TOO_LONG", "name", SEVERITY_INFO, 3,
        f"Ürün başlığı {MAX_TITLE_LEN} karakterden uzun.",
        "Başlığı özet bilgilere göre kısaltın.",
    ),
    "TITLE_EXCESSIVE_UPPERCASE": IssueDef(
        "TITLE_EXCESSIVE_UPPERCASE", "name", SEVERITY_WARNING, 5,
        "Başlıkta çok fazla büyük harf var.",
        "Başlığı normal cümle veya başlık düzeninde yazın.",
    ),
    "TITLE_REPEATED_WORDS": IssueDef(
        "TITLE_REPEATED_WORDS", "name", SEVERITY_INFO, 3,
        "Başlıkta tekrar eden kelimeler var.",
        "Aynı kelimeyi tek seferde yazın; gereksiz tekrarları temizleyin.",
    ),
    "GENERIC_TITLE": IssueDef(
        "GENERIC_TITLE", "name", SEVERITY_WARNING, 6,
        "Başlık aşırı genel görünüyor.",
        "Marka, model veya ürüne özgü bilgi ekleyerek başlığı belirginleştirin.",
    ),
    "INVALID_STOCK": IssueDef(
        "INVALID_STOCK", "stock", SEVERITY_WARNING, 5,
        "Stok değeri geçersiz.", "Stoku 0 veya pozitif bir tam sayı olarak ayarlayın.",
    ),
    "DUPLICATE_TITLE": IssueDef(
        "DUPLICATE_TITLE", "name", SEVERITY_WARNING, 8,
        "Katalogda aynı başlığa sahip başka bir ürün var.",
        "Başlıkları birbirinden ayırt etmek için model, renk veya beden ekleyin.",
    ),
}


# ---------------- Helpers ----------------
def _norm_title(s: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _is_valid_http_url(u: Optional[str]) -> bool:
    if not u:
        return False
    return bool(re.match(r"^https?://[^\s]+$", u.strip()))


def _uppercase_ratio(s: str) -> float:
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return 0.0
    upper = sum(1 for c in letters if c.isupper())
    return upper / len(letters)


def _has_repeated_words(s: str) -> bool:
    tokens = [t.lower() for t in re.findall(r"[A-Za-zĞÜŞİÖÇğüşıöç]+", s or "") if len(t) > 3]
    if len(tokens) < 3:
        return False
    seen: dict[str, int] = {}
    for t in tokens:
        seen[t] = seen.get(t, 0) + 1
    return any(v >= 2 for v in seen.values())


def _is_generic_title(s: str) -> bool:
    nt = _norm_title(s)
    if not nt:
        return True
    if len(nt.split()) <= 2 and any(g in nt for g in GENERIC_TITLE_TOKENS):
        return True
    return False


# ---------------- Public API ----------------
def check_product(product: Product, other_titles: Iterable[str] = ()) -> List[dict]:
    """Return the list of active issues (as dicts) for a product."""
    issues: List[dict] = []

    def add(code: str, **overrides):
        d = ISSUE_CATALOG[code]
        issues.append({
            "code": d.code,
            "field": overrides.get("field", d.field),
            "severity": d.severity,
            "message": overrides.get("message", d.message),
            "recommendation": d.recommendation,
            "weight": d.weight,
        })

    if not (product.sku or "").strip():
        add("MISSING_SKU")
    if not (product.name or "").strip():
        add("MISSING_NAME")

    name = product.name or ""
    if name:
        if len(name.strip()) < MIN_TITLE_LEN:
            add("TITLE_TOO_SHORT")
        if len(name.strip()) > MAX_TITLE_LEN:
            add("TITLE_TOO_LONG")
        if _uppercase_ratio(name) > UPPERCASE_THRESHOLD and len(name) > 6:
            add("TITLE_EXCESSIVE_UPPERCASE")
        if _has_repeated_words(name):
            add("TITLE_REPEATED_WORDS")
        if _is_generic_title(name):
            add("GENERIC_TITLE")

    desc = (product.description or "").strip()
    if not desc:
        add("MISSING_DESCRIPTION")
    elif len(desc) < MIN_DESCRIPTION_LEN:
        add("SHORT_DESCRIPTION")

    if product.price is None:
        add("MISSING_PRICE")
    elif product.price <= 0:
        add("INVALID_PRICE")

    if not (product.category or "").strip():
        add("MISSING_CATEGORY")

    if not (product.image_url or "").strip():
        add("MISSING_IMAGE")
    elif not _is_valid_http_url(product.image_url):
        add("INVALID_IMAGE_URL")

    if not (product.product_url or "").strip():
        add("MISSING_PRODUCT_URL")

    if product.stock is None or product.stock < 0:
        add("INVALID_STOCK")

    # Duplicate title within the catalog
    nt = _norm_title(name)
    if nt and any(_norm_title(other) == nt for other in other_titles):
        add("DUPLICATE_TITLE")

    return issues


def compute_score(issues: List[dict]) -> int:
    score = 100
    for it in issues:
        score -= it["weight"]
    return max(0, min(100, score))


def analyze_product(db: Session, product: Product, *, actor_source: str = "quality_engine") -> dict:
    """Run analysis on a single product, persist issues, update product row.

    Idempotent: does not duplicate unresolved issues. Returns
    {score, issues:[{code,severity,field,message,recommendation}], previous_score}.
    """
    others = (
        row[0] for row in db.query(Product.name)
        .filter(Product.id != product.id, Product.name.isnot(None))
        .all()
    )
    active = check_product(product, other_titles=others)
    score = compute_score(active)

    # Replace current unresolved issues with the fresh set (idempotent).
    db.query(ProductIssue).filter(
        ProductIssue.product_id == product.id, ProductIssue.is_resolved.is_(False)
    ).delete(synchronize_session=False)

    for it in active:
        db.add(ProductIssue(
            product_id=product.id,
            issue_code=it["code"],
            field_name=it["field"],
            severity=it["severity"],
            message=it["message"],
            recommendation=it["recommendation"],
            is_resolved=False,
        ))

    previous = product.quality_score
    product.quality_score = score
    product.quality_analyzed_at = datetime.now(timezone.utc)
    db.flush()

    return {"score": score, "previous_score": previous, "issues": active}
