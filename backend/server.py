"""AI Merchant OS Lite - FastAPI backend (SQLite, Phase 1 hardened)."""
from __future__ import annotations

import csv
import io
import logging
import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, List, Optional

from defusedxml.ElementTree import fromstring as _xml_fromstring
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import or_, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.middleware.cors import CORSMiddleware

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

from database import Base, SessionLocal, engine, get_db  # noqa: E402,F401
from models import Activity, Meta, Product, ProductIssue, ProductSuggestion  # noqa: E402
import ai_service  # noqa: E402
from ai_service import AIProviderError  # noqa: E402
import merchant_routes  # noqa: E402
import merchant_service  # noqa: E402
import woocommerce_routes  # noqa: E402
from merchant_service import STATUS_LABELS  # noqa: E402
from sample_data import seed as seed_samples  # noqa: E402

logger = logging.getLogger("merchant-os")
logging.basicConfig(level=logging.INFO)


# --- Config --------------------------------------------------------------
MAX_FILE_MB = float(os.environ.get("IMPORT_MAX_FILE_MB", "10"))
MAX_ROWS = int(os.environ.get("IMPORT_MAX_ROWS", "10000"))
MAX_CELL_LEN = 20_000
PRICE_PCT_LIMIT = float(os.environ.get("BULK_PRICE_PERCENT_LIMIT", "90"))

ALLOWED_EXTS = {".csv", ".xml"}
ALLOWED_MIMES = {
    "text/csv", "application/csv", "application/vnd.ms-excel",
    "text/plain",
    "application/xml", "text/xml",
    "application/octet-stream",  # some browsers upload CSVs this way
}


# --- App bootstrap -------------------------------------------------------
app = FastAPI(title="AI Merchant OS Lite")
api = APIRouter(prefix="/api")


def _run_migrations() -> None:
    """Bring the database schema up to head via Alembic.

    Alembic is the sole schema migration mechanism in production.
    Tests may bypass this via DISABLE_MIGRATIONS=1 and create tables directly
    against a temporary database.
    """
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(ROOT_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT_DIR / "alembic"))
    sqlite_path = os.environ.get("SQLITE_PATH", str(ROOT_DIR / "merchant_os.db"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{sqlite_path}")
    command.upgrade(cfg, "head")


@app.on_event("startup")
def _startup() -> None:
    if os.environ.get("DISABLE_MIGRATIONS", "").lower() not in ("1", "true", "yes"):
        _run_migrations()
    if os.environ.get("DISABLE_SAMPLE_SEED", "").lower() in ("1", "true", "yes"):
        return
    db = SessionLocal()
    try:
        n = seed_samples(db)
        if n:
            logger.info("Seeded %d sample products", n)
    finally:
        db.close()


# --- Helpers -------------------------------------------------------------
def _iso_utc(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def _now_iso() -> str:
    return _iso_utc(datetime.now(timezone.utc))  # type: ignore[return-value]


def _log_activity(db: Session, kind: str, message: str) -> None:
    db.add(Activity(kind=kind, message=message))


def _to_float(value: Any) -> Optional[float]:
    """Parse numbers in TR/US formats: 1.234,56 | 1234,56 | 1,234.56 | 1234.56"""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    # Strip currency symbols / spaces but keep digits, dot, comma, minus.
    s = re.sub(r"[^\d,.\-]", "", s)
    if not s:
        return None
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        if len(parts) == 2 and len(parts[1]) <= 2:
            s = parts[0].replace(",", "") + "." + parts[1]
        else:
            s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def _to_int(value: Any) -> Optional[int]:
    f = _to_float(value)
    if f is None:
        return None
    try:
        return int(f)
    except (TypeError, ValueError):
        return None


def _tr_norm(text_: str) -> str:
    """Turkish-aware lowercase + ASCII fold for column matching."""
    if not text_:
        return ""
    mapping = str.maketrans({
        "ı": "i", "İ": "i", "I": "i",
        "ş": "s", "Ş": "s",
        "ğ": "g", "Ğ": "g",
        "ü": "u", "Ü": "u",
        "ö": "o", "Ö": "o",
        "ç": "c", "Ç": "c",
    })
    s = text_.translate(mapping).lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", s)


_COLUMN_HINTS: dict[str, list[str]] = {
    "sku": ["sku", "stokkodu", "urunkodu", "kod", "code", "productcode"],
    "name": ["urunadi", "urun", "urunismi", "name", "title", "productname", "baslik", "ad"],
    "description": ["aciklama", "description", "desc", "urunaciklamasi"],
    "category": ["kategori", "category", "kategoriadi"],
    "price": ["fiyat", "price", "satisfiyati", "urunfiyati"],
    "stock": ["stok", "stock", "adet", "quantity", "qty", "stokadet"],
    "image_url": ["gorselurl", "gorsel", "resim", "resimurl", "imageurl", "image", "picture", "photo"],
    "product_url": ["urunurl", "urunlinki", "urunbaglantisi", "producturl", "link", "url"],
}


def _guess_mapping(columns: List[str]) -> tuple[dict, dict]:
    """Return (mapping, confidence) - confidence is 'high' or 'low'."""
    mapping: dict = {}
    confidence: dict = {}
    used: set[str] = set()
    normalized = [(col, _tr_norm(col)) for col in columns]
    for field, hints in _COLUMN_HINTS.items():
        best: Optional[tuple[str, str]] = None  # (col, level)
        for col, nc in normalized:
            if col in used or not nc:
                continue
            for h in hints:
                if nc == h:
                    best = (col, "high"); break
            if best and best[1] == "high":
                break
            if not best:
                for h in hints:
                    if h in nc:
                        best = (col, "low"); break
        if best:
            mapping[field] = best[0]
            confidence[field] = best[1]
            used.add(best[0])
    return mapping, confidence


def _validate_url(u: Optional[str]) -> Optional[str]:
    if u is None:
        return None
    s = str(u).strip()
    if not s:
        return None
    if not re.match(r"^https?://[^\s]+$", s):
        raise ValueError("URL http:// veya https:// ile başlamalıdır")
    return s


def _normalize_sku(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


# --- Schemas -------------------------------------------------------------
class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    sku: str
    name: str
    improved_name: Optional[str] = None
    description: Optional[str] = None
    improved_description: Optional[str] = None
    category: Optional[str] = None
    price: Optional[float] = None
    stock: Optional[int] = 0
    image_url: Optional[str] = None
    product_url: Optional[str] = None
    is_edited: bool = False
    workflow_status: str = "imported"
    quality_score: Optional[int] = None
    quality_analyzed_at: Optional[datetime] = None
    active_suggestion_id: Optional[str] = None
    updated_at: datetime

    def to_dict(self) -> dict:
        d = self.model_dump()
        d["updated_at"] = _iso_utc(self.updated_at)
        d["quality_analyzed_at"] = _iso_utc(self.quality_analyzed_at)
        d["workflow_status_label"] = STATUS_LABELS.get(self.workflow_status, self.workflow_status)
        return d


class ProductUpdate(BaseModel):
    sku: Optional[str] = None
    improved_name: Optional[str] = None
    improved_description: Optional[str] = None
    category: Optional[str] = None
    price: Optional[float] = Field(default=None, ge=0)
    stock: Optional[int] = Field(default=None, ge=0)
    image_url: Optional[str] = None
    product_url: Optional[str] = None

    @field_validator("image_url", "product_url")
    @classmethod
    def _urls(cls, v):
        return _validate_url(v)

    @field_validator("sku")
    @classmethod
    def _sku(cls, v):
        if v is None:
            return v
        s = _normalize_sku(v)
        if not s:
            raise ValueError("SKU boş olamaz")
        return s


class MappingIn(BaseModel):
    mapping: dict
    rows: List[dict] = Field(min_length=1, max_length=MAX_ROWS)
    mode: str = Field(default="fill_empty", pattern="^(fill_empty|replace)$")


class BulkIdsIn(BaseModel):
    ids: List[str] = Field(min_length=1)


class BulkCategoryIn(BulkIdsIn):
    category: str = Field(min_length=1, max_length=120)


class BulkPricePctIn(BulkIdsIn):
    percent: float

    @field_validator("percent")
    @classmethod
    def _range(cls, v):
        if abs(v) > PRICE_PCT_LIMIT:
            raise ValueError(f"Yüzde ±{PRICE_PCT_LIMIT} sınırını aşamaz")
        return v


class BulkImproveIn(BulkIdsIn):
    kind: str = Field(pattern="^(title|description|both)$")


class ImproveIn(BaseModel):
    kind: str = Field(pattern="^(title|description|both)$")


# --- File parsing --------------------------------------------------------
def _decode_bytes(content: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1254", "iso-8859-9"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    raise HTTPException(400, "Dosya kodlaması okunamadı (UTF-8, Windows-1254 veya ISO-8859-9 bekleniyor)")


def _parse_csv(content: bytes) -> tuple[List[str], List[dict]]:
    text_ = _decode_bytes(content)
    if not text_.strip():
        raise HTTPException(400, "Dosya boş")
    sample = text_[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delim = dialect.delimiter
    except csv.Error:
        delim = ","
    reader = csv.reader(io.StringIO(text_), delimiter=delim)
    header: Optional[List[str]] = None
    rows: List[dict] = []
    for i, raw in enumerate(reader):
        if header is None:
            header = [str(c).strip() for c in raw]
            if not header or all(h == "" for h in header):
                raise HTTPException(400, "CSV başlık satırı bulunamadı")
            continue
        if len(rows) >= MAX_ROWS:
            raise HTTPException(400, f"Satır limiti aşıldı (en fazla {MAX_ROWS})")
        row = {}
        for idx, col in enumerate(header):
            val = raw[idx] if idx < len(raw) else ""
            if isinstance(val, str) and len(val) > MAX_CELL_LEN:
                raise HTTPException(400, f"Hücre boyutu limiti aşıldı (satır {i + 1})")
            row[col] = val
        rows.append(row)
    if not rows:
        raise HTTPException(400, "CSV içinde veri satırı bulunamadı")
    return header, rows


def _find_product_nodes(root) -> list:
    """Detect the repeated product element in an XML tree.

    Handles common shapes:
      - <products><product/></products>
      - <items><item/></items>
      - <rss><channel><item/></channel></rss>
      - Google Merchant style feeds
      - Files with XML namespaces
    """
    # Explicit shortcuts
    for xp in ("./channel/item", "./channel/{*}item", "./{*}channel/{*}item"):
        try:
            nodes = root.findall(xp)
        except SyntaxError:
            nodes = []
        if len(nodes) >= 1:
            return nodes
    # Common wrappers
    for xp in ("./product", "./item", "./{*}product", "./{*}item"):
        try:
            nodes = root.findall(xp)
        except SyntaxError:
            nodes = []
        if len(nodes) >= 1:
            return nodes
    # Fallback: most frequently repeated non-leaf tag anywhere in the tree
    counts: dict[str, list] = {}
    for el in root.iter():
        for child in el:
            if len(list(child)) == 0:
                continue  # skip leaves
            tag = child.tag.split("}")[-1]
            counts.setdefault(tag, []).append(child)
    if not counts:
        return []
    tag, nodes = max(counts.items(), key=lambda x: len(x[1]))
    return nodes if len(nodes) >= 2 else []


def _parse_xml(content: bytes) -> tuple[List[str], List[dict]]:
    text_ = _decode_bytes(content)
    try:
        root = _xml_fromstring(text_)
    except Exception as exc:
        raise HTTPException(400, f"XML çözümlenemedi: {exc}")
    nodes = _find_product_nodes(root)
    if not nodes:
        raise HTTPException(
            400,
            "XML yapısı algılanamadı. Beklenen yapılar: "
            "<products><product>, <items><item>, <rss><channel><item> veya "
            "benzeri tekrarlanan ürün öğeleri.",
        )
    if len(nodes) > MAX_ROWS:
        raise HTTPException(400, f"Satır limiti aşıldı (en fazla {MAX_ROWS})")
    rows: List[dict] = []
    cols: List[str] = []
    for item in nodes:
        row: dict = {}
        for child in item:
            tag = child.tag.split("}")[-1]
            val = (child.text or "").strip()
            if len(val) > MAX_CELL_LEN:
                raise HTTPException(400, f"Hücre boyutu limiti aşıldı ({tag})")
            row[tag] = val
            if tag not in cols:
                cols.append(tag)
        for k, v in item.attrib.items():
            key = k.split("}")[-1]
            if key not in row:
                row[key] = v
                if key not in cols:
                    cols.append(key)
        rows.append(row)
    return cols, rows


def _validate_upload(file: UploadFile, content: bytes) -> str:
    """Validate extension, MIME and size. Returns the detected format."""
    name = (file.filename or "").lower()
    ext = os.path.splitext(name)[1]
    if ext not in ALLOWED_EXTS:
        raise HTTPException(400, "Desteklenmeyen dosya türü. Yalnızca CSV ve XML kabul edilir.")
    mime = (file.content_type or "").lower().split(";")[0].strip()
    if mime and mime not in ALLOWED_MIMES:
        # Extension-based fallback allowed, but flag suspicious mismatches for XML.
        if ext == ".xml" and "xml" not in mime and mime != "application/octet-stream":
            raise HTTPException(400, f"Beklenmeyen MIME türü: {mime}")
    if not content:
        raise HTTPException(400, "Dosya boş")
    max_bytes = int(MAX_FILE_MB * 1024 * 1024)
    if len(content) > max_bytes:
        raise HTTPException(400, f"Dosya boyutu limiti aşıldı ({MAX_FILE_MB} MB)")
    return "xml" if ext == ".xml" else "csv"


# --- Endpoints -----------------------------------------------------------
@api.get("/health")
def health():
    return {
        "status": "ok",
        "demo_mode": ai_service.is_demo_mode(),
        "gemini_model": ai_service.gemini_model() if not ai_service.is_demo_mode() else None,
    }


@api.get("/dashboard/stats")
def dashboard_stats(db: Session = Depends(get_db)):
    from sqlalchemy import func
    total = db.query(Product).count()
    missing_desc = db.query(Product).filter(
        or_(Product.description.is_(None), Product.description == "")
    ).count()
    missing_price = db.query(Product).filter(Product.price.is_(None)).count()
    edited = db.query(Product).filter(Product.is_edited.is_(True)).count()
    last_import = db.query(Meta).filter(Meta.key == "last_import_at").first()

    avg_row = db.query(func.avg(Product.quality_score)).filter(Product.quality_score.isnot(None)).first()
    avg_score = float(avg_row[0]) if avg_row and avg_row[0] is not None else None
    by_status = dict(
        db.query(Product.workflow_status, func.count(Product.id))
        .group_by(Product.workflow_status).all()
    )
    critical_open = db.query(func.count(ProductIssue.id)).filter(
        ProductIssue.severity == "critical", ProductIssue.is_resolved.is_(False)
    ).scalar() or 0

    activities = (
        db.query(Activity).order_by(Activity.created_at.desc()).limit(10).all()
    )
    return {
        "total_products": total,
        "missing_description": missing_desc,
        "missing_price": missing_price,
        "edited_products": edited,
        "last_import_at": last_import.value if last_import else None,
        "average_quality_score": round(avg_score, 1) if avg_score is not None else None,
        "needs_attention": by_status.get("needs_attention", 0),
        "awaiting_review": by_status.get("awaiting_review", 0),
        "ready_for_ai": by_status.get("ready_for_ai", 0),
        "approved": by_status.get("approved", 0),
        "ready_to_publish": by_status.get("ready_to_publish", 0),
        "imported": by_status.get("imported", 0),
        "open_critical_issues": critical_open,
        "recent_activities": [
            {
                "id": a.id,
                "kind": a.kind,
                "message": a.message,
                "created_at": _iso_utc(a.created_at),
            }
            for a in activities
        ],
    }


# --- Products ------------------------------------------------------------
def _apply_filters(query, q, category, missing_desc, missing_price, in_stock, edited,
                   workflow_status=None, score_bucket=None):
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Product.name.ilike(like), Product.sku.ilike(like)))
    if category:
        query = query.filter(Product.category == category)
    if missing_desc:
        query = query.filter(or_(Product.description.is_(None), Product.description == ""))
    if missing_price:
        query = query.filter(Product.price.is_(None))
    if in_stock:
        query = query.filter(Product.stock > 0)
    if edited:
        query = query.filter(Product.is_edited.is_(True))
    if workflow_status:
        query = query.filter(Product.workflow_status == workflow_status)
    if score_bucket == "low":
        query = query.filter(Product.quality_score < 60)
    elif score_bucket == "mid":
        query = query.filter(Product.quality_score >= 60, Product.quality_score < 85)
    elif score_bucket == "high":
        query = query.filter(Product.quality_score >= 85)
    elif score_bucket == "critical":
        query = query.join(
            ProductIssue, ProductIssue.product_id == Product.id
        ).filter(ProductIssue.severity == "critical", ProductIssue.is_resolved.is_(False)).distinct()
    return query


@api.get("/products")
def list_products(
    q: Optional[str] = None,
    category: Optional[str] = None,
    missing_desc: bool = False,
    missing_price: bool = False,
    in_stock: bool = False,
    edited: bool = False,
    workflow_status: Optional[str] = None,
    score_bucket: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
):
    query = _apply_filters(db.query(Product), q, category, missing_desc, missing_price,
                            in_stock, edited, workflow_status, score_bucket)
    total = query.count()
    items = (
        query.order_by(Product.updated_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    # Attach unresolved issue counts in one query.
    ids = [p.id for p in items]
    counts: dict[str, int] = {}
    if ids:
        from sqlalchemy import func
        rows = (db.query(ProductIssue.product_id, func.count(ProductIssue.id))
                .filter(ProductIssue.product_id.in_(ids), ProductIssue.is_resolved.is_(False))
                .group_by(ProductIssue.product_id).all())
        counts = {pid: c for pid, c in rows}
    result_items = []
    for p in items:
        d = ProductOut.model_validate(p).to_dict()
        d["issue_count"] = counts.get(p.id, 0)
        result_items.append(d)
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": result_items,
    }


@api.get("/products/categories")
def categories(db: Session = Depends(get_db)):
    rows = db.query(Product.category).filter(Product.category.isnot(None)).distinct().all()
    return sorted([r[0] for r in rows if r[0]])


@api.get("/products/{pid}")
def get_product(pid: str, db: Session = Depends(get_db)):
    p = db.get(Product, pid)
    if not p:
        raise HTTPException(404, "Ürün bulunamadı")
    return ProductOut.model_validate(p).to_dict()


@api.patch("/products/{pid}")
def update_product(pid: str, payload: ProductUpdate, db: Session = Depends(get_db)):
    p = db.get(Product, pid)
    if not p:
        raise HTTPException(404, "Ürün bulunamadı")
    data = payload.model_dump(exclude_unset=True)
    if "sku" in data:
        new_sku = _normalize_sku(data["sku"])
        if new_sku != p.sku:
            dup = db.query(Product).filter(Product.sku == new_sku, Product.id != pid).first()
            if dup:
                raise HTTPException(409, f"SKU zaten kullanılıyor: {new_sku}")
        data["sku"] = new_sku
    for k, v in data.items():
        setattr(p, k, v)
    p.is_edited = True
    # Phase 2.1: direct edits must re-run analysis + refresh workflow status
    # (including re-checking publish readiness for approved suggestions).
    merchant_service.analyze_and_transition(db, p)
    _log_activity(db, "edit", f"Ürün güncellendi: {p.sku}")
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "SKU zaten kullanılıyor")
    db.refresh(p)
    return ProductOut.model_validate(p).to_dict()


@api.post("/products/{pid}/revert")
def revert_product(pid: str, db: Session = Depends(get_db)):
    p = db.get(Product, pid)
    if not p:
        raise HTTPException(404, "Ürün bulunamadı")
    p.improved_name = None
    p.improved_description = None
    p.is_edited = False
    _log_activity(db, "edit", f"Ürün orijinaline döndürüldü: {p.sku}")
    db.commit()
    db.refresh(p)
    return ProductOut.model_validate(p).to_dict()


@api.post("/products/{pid}/improve")
async def improve_product(pid: str, payload: ImproveIn, db: Session = Depends(get_db)):
    p = db.get(Product, pid)
    if not p:
        raise HTTPException(404, "Ürün bulunamadı")
    try:
        if payload.kind in ("title", "both"):
            p.improved_name = await ai_service.improve_title(p.name, p.category)
        if payload.kind in ("description", "both"):
            p.improved_description = await ai_service.improve_description(
                p.improved_name or p.name, p.category, p.description
            )
    except AIProviderError as exc:
        raise HTTPException(502, f"AI sağlayıcı hatası: {exc}")
    p.is_edited = True
    _log_activity(db, "edit", f"AI ile iyileştirildi ({payload.kind}): {p.sku}")
    db.commit()
    db.refresh(p)
    return ProductOut.model_validate(p).to_dict()


# --- Import --------------------------------------------------------------
@api.post("/import/preview")
async def import_preview(file: UploadFile = File(...)):
    content = await file.read()
    fmt = _validate_upload(file, content)
    if fmt == "xml":
        cols, rows = _parse_xml(content)
    else:
        cols, rows = _parse_csv(content)
    mapping, confidence = _guess_mapping(cols)
    return {
        "format": fmt,
        "columns": cols,
        "sample": rows[:5],
        "total_rows": len(rows),
        "rows": rows,
        "suggested_mapping": mapping,
        "mapping_confidence": confidence,
    }


@api.post("/import/commit")
def import_commit(payload: MappingIn, db: Session = Depends(get_db)):
    mapping = payload.mapping or {}
    if not mapping.get("sku") or not mapping.get("name"):
        raise HTTPException(400, "SKU ve Ürün Adı eşleştirmesi zorunludur")

    mode = payload.mode  # fill_empty | replace
    inserted = updated = skipped = failed = 0
    errors: list[dict] = []
    _MAPPED_FIELDS = ("name", "description", "category", "price", "stock", "image_url", "product_url")

    def _get(row: dict, field: str) -> Any:
        col = mapping.get(field)
        return row.get(col) if col else None

    def _field_is_empty(field: str, val: Any) -> bool:
        if val is None:
            return True
        if isinstance(val, str) and val == "":
            return True
        if field == "stock" and val == 0:
            return True
        return False

    for idx, row in enumerate(payload.rows, start=1):
        # Each row runs inside its own SAVEPOINT so a failure rolls back only
        # this row's changes — previously successful inserts/updates persist
        # and the counters remain accurate.
        try:
            with db.begin_nested():
                sku = _normalize_sku(_get(row, "sku"))
                name_val = str(_get(row, "name") or "").strip()
                if not sku:
                    raise ValueError("SKU boş")
                if not name_val:
                    raise ValueError("Ürün adı boş")

                price_raw = _get(row, "price") if "price" in mapping else None
                price = _to_float(price_raw) if price_raw not in (None, "") else None
                if price is not None and price < 0:
                    raise ValueError("Fiyat negatif olamaz")

                stock_raw = _get(row, "stock") if "stock" in mapping else None
                stock = _to_int(stock_raw) if stock_raw not in (None, "") else None
                if stock is not None and stock < 0:
                    raise ValueError("Stok negatif olamaz")

                image_url = _validate_url(_get(row, "image_url")) if "image_url" in mapping else None
                product_url = _validate_url(_get(row, "product_url")) if "product_url" in mapping else None

                new_values = {
                    "sku": sku,
                    "name": name_val,
                    "description": (str(_get(row, "description") or "").strip() or None) if "description" in mapping else None,
                    "category": (str(_get(row, "category") or "").strip() or None) if "category" in mapping else None,
                    "price": price,
                    "stock": stock,
                    "image_url": image_url,
                    "product_url": product_url,
                }

                existing = db.query(Product).filter(Product.sku == sku).first()
                if existing:
                    changed = False
                    for field in _MAPPED_FIELDS:
                        if field not in mapping:
                            continue  # unmapped -> preserve existing
                        incoming = new_values[field]
                        current = getattr(existing, field)
                        if mode == "fill_empty":
                            if _field_is_empty(field, incoming):
                                continue  # nothing to fill with
                            if not _field_is_empty(field, current):
                                continue  # existing value wins
                        # mode == replace, or fill_empty with empty current
                        if current == incoming:
                            continue  # no actual change
                        setattr(existing, field, incoming)
                        changed = True
                    if changed:
                        existing.is_edited = True
                        updated += 1
                    else:
                        skipped += 1
                else:
                    if new_values["stock"] is None:
                        new_values["stock"] = 0
                    db.add(Product(**new_values))
                    db.flush()  # surface SKU to subsequent queries in this batch
                    inserted += 1
        except ValueError as exc:
            failed += 1
            errors.append({"row": idx, "message": str(exc)})
        except IntegrityError as exc:
            # SAVEPOINT already rolled back — prior rows are untouched.
            failed += 1
            errors.append({"row": idx, "message": f"Veritabanı hatası: {exc.orig}"})

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, f"İçe aktarma başarısız (bütünlük hatası): {exc.orig}")

    now = _now_iso()
    db.merge(Meta(key="last_import_at", value=now))
    _log_activity(
        db, "import",
        f"İçe aktarma: +{inserted} yeni, {updated} güncelleme, {skipped} atlandı, {failed} hata",
    )
    db.commit()

    # Auto-analyze touched products (silent — no separate activity log).
    sku_col = mapping.get("sku")
    touched_skus = set()
    if sku_col:
        for r in payload.rows:
            raw = r.get(sku_col)
            if raw:
                s = _normalize_sku(raw)
                if s:
                    touched_skus.add(s)
    if touched_skus:
        touched = db.query(Product).filter(Product.sku.in_(touched_skus)).all()
        for p in touched:
            merchant_service.analyze_and_transition(db, p)
        db.commit()

    return {
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "failed": failed,
        "errors": errors[:100],
        "mode": mode,
    }


@api.get("/import/sample")
def import_sample():
    buf = io.StringIO()
    buf.write("\ufeff")
    writer = csv.writer(buf)
    writer.writerow(["sku", "name", "description", "category", "price", "stock", "image_url", "product_url"])
    writer.writerow(["ORNK-001", "Örnek Ürün Adı", "Kısa Türkçe açıklama.", "Elektronik", "1299.90", "10",
                     "https://example.com/gorsel.jpg", "https://example.com/urun"])
    writer.writerow(["ORNK-002", "İkinci Örnek Ürün", "", "Giyim", "", "5", "", ""])
    data = buf.getvalue().encode("utf-8")
    return StreamingResponse(
        io.BytesIO(data),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=ornek-urunler.csv"},
    )


# --- Bulk ---------------------------------------------------------------
@api.post("/bulk/improve-products")
async def bulk_improve_products(payload: BulkImproveIn, db: Session = Depends(get_db)):
    products = db.query(Product).filter(Product.id.in_(payload.ids)).all()
    try:
        for p in products:
            if payload.kind in ("title", "both"):
                p.improved_name = await ai_service.improve_title(p.name, p.category)
            if payload.kind in ("description", "both"):
                p.improved_description = await ai_service.improve_description(
                    p.improved_name or p.name, p.category, p.description
                )
            p.is_edited = True
    except AIProviderError as exc:
        db.rollback()
        raise HTTPException(502, f"AI sağlayıcı hatası: {exc}")
    _log_activity(db, "bulk", f"Toplu iyileştirme ({payload.kind}): {len(products)} ürün")
    db.commit()
    return {"updated": len(products)}


@api.post("/bulk/category")
def bulk_category(payload: BulkCategoryIn, db: Session = Depends(get_db)):
    products = db.query(Product).filter(Product.id.in_(payload.ids)).all()
    changed_ids: list[str] = []
    for p in products:
        if p.category != payload.category:
            p.category = payload.category
            p.is_edited = True
            changed_ids.append(p.id)
    # Re-analyze only products whose value actually changed.
    for p in products:
        if p.id in changed_ids:
            merchant_service.analyze_and_transition(db, p)
    _log_activity(db, "bulk", f"Kategori atandı ({payload.category}): {len(changed_ids)} ürün")
    db.commit()
    return {"updated": len(changed_ids)}


@api.post("/bulk/price-percent")
def bulk_price_percent(payload: BulkPricePctIn, db: Session = Depends(get_db)):
    products = db.query(Product).filter(Product.id.in_(payload.ids)).all()
    changed_ids: list[str] = []
    factor = 1 + (payload.percent / 100.0)
    for p in products:
        if p.price is None:
            continue
        new_price = round(p.price * factor, 2)
        if new_price < 0:
            continue  # never persist a negative price
        if new_price == p.price:
            continue  # nothing actually changed
        p.price = new_price
        p.is_edited = True
        changed_ids.append(p.id)
    # Re-analyze only products whose value actually changed.
    for p in products:
        if p.id in changed_ids:
            merchant_service.analyze_and_transition(db, p)
    _log_activity(db, "bulk", f"Fiyat %{payload.percent} güncellendi: {len(changed_ids)} ürün")
    db.commit()
    return {"updated": len(changed_ids)}


# --- Export --------------------------------------------------------------
def _csv_response(products: Iterable[Product]) -> StreamingResponse:
    buf = io.StringIO()
    buf.write("\ufeff")
    writer = csv.writer(buf)
    writer.writerow(
        ["sku", "name", "improved_name", "description", "improved_description",
         "category", "price", "stock", "image_url", "product_url"]
    )
    for p in products:
        writer.writerow([
            p.sku, p.name, p.improved_name or "",
            p.description or "", p.improved_description or "",
            p.category or "", "" if p.price is None else p.price,
            p.stock if p.stock is not None else "",
            p.image_url or "", p.product_url or "",
        ])
    data = buf.getvalue().encode("utf-8")
    return StreamingResponse(
        io.BytesIO(data),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=urunler.csv"},
    )


@api.get("/export/all")
def export_all(db: Session = Depends(get_db)):
    products = db.query(Product).all()
    _log_activity(db, "export", f"Tüm ürünler dışa aktarıldı: {len(products)}")
    db.commit()
    return _csv_response(products)


@api.post("/export/selected")
def export_selected(payload: BulkIdsIn, db: Session = Depends(get_db)):
    products = db.query(Product).filter(Product.id.in_(payload.ids)).all()
    _log_activity(db, "export", f"Seçili ürünler dışa aktarıldı: {len(products)}")
    db.commit()
    return _csv_response(products)


@api.get("/export/filtered")
def export_filtered(
    q: Optional[str] = None,
    category: Optional[str] = None,
    missing_desc: bool = False,
    missing_price: bool = False,
    in_stock: bool = False,
    edited: bool = False,
    db: Session = Depends(get_db),
):
    query = _apply_filters(db.query(Product), q, category, missing_desc, missing_price, in_stock, edited)
    products = query.all()
    _log_activity(db, "export", f"Filtrelenmiş ürünler dışa aktarıldı: {len(products)}")
    db.commit()
    return _csv_response(products)


# --- App wiring ----------------------------------------------------------
app.include_router(api)
app.include_router(merchant_routes.router)
app.include_router(woocommerce_routes.router)
app.include_router(woocommerce_routes.publish_router)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)
