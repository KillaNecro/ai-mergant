"""AI Merchant OS Lite - FastAPI backend (SQLite)."""
from __future__ import annotations

import csv
import io
import logging
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session
from starlette.middleware.cors import CORSMiddleware

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

from database import Base, SessionLocal, engine, get_db  # noqa: E402
from models import Activity, Meta, Product  # noqa: E402
import ai_service  # noqa: E402
from sample_data import seed as seed_samples  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("merchant-os")

# --- App bootstrap --------------------------------------------------------
Base.metadata.create_all(bind=engine)

app = FastAPI(title="AI Merchant OS Lite")
api = APIRouter(prefix="/api")


@app.on_event("startup")
def _startup():
    db = SessionLocal()
    try:
        n = seed_samples(db)
        if n:
            logger.info("Seeded %d sample products", n)
    finally:
        db.close()


# --- Schemas --------------------------------------------------------------
class ProductOut(BaseModel):
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
    updated_at: datetime

    class Config:
        from_attributes = True


class ProductUpdate(BaseModel):
    sku: Optional[str] = None
    name: Optional[str] = None
    improved_name: Optional[str] = None
    description: Optional[str] = None
    improved_description: Optional[str] = None
    category: Optional[str] = None
    price: Optional[float] = None
    stock: Optional[int] = None
    image_url: Optional[str] = None
    product_url: Optional[str] = None


class MappingIn(BaseModel):
    mapping: dict  # target_field -> source_column
    rows: List[dict]


class BulkIdsIn(BaseModel):
    ids: List[str]


class BulkCategoryIn(BulkIdsIn):
    category: str


class BulkPricePctIn(BulkIdsIn):
    percent: float  # positive=increase, negative=decrease


class ImproveIn(BaseModel):
    kind: str = Field(..., pattern="^(title|description|both)$")


# --- Helpers --------------------------------------------------------------
FIELDS = ["sku", "name", "description", "category", "price", "stock", "image_url", "product_url"]


def _log_activity(db: Session, kind: str, message: str):
    db.add(Activity(kind=kind, message=message))


def _to_float(v) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        s = str(v).replace(".", "").replace(",", ".") if str(v).count(",") == 1 and str(v).count(".") <= 1 else str(v).replace(",", ".")
        return float(s)
    except (TypeError, ValueError):
        try:
            return float(str(v).replace(",", "."))
        except Exception:
            return None


def _to_int(v) -> Optional[int]:
    if v is None or v == "":
        return None
    try:
        return int(float(str(v).replace(",", ".")))
    except Exception:
        return None


def _parse_csv(content: bytes) -> tuple[List[str], List[dict]]:
    # Try UTF-8 first, then Windows-1254 (Turkish)
    text = None
    for enc in ("utf-8-sig", "utf-8", "cp1254", "iso-8859-9"):
        try:
            text = content.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise HTTPException(400, "Dosya kodlaması okunamadı")
    # Sniff delimiter
    sample = text[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delim = dialect.delimiter
    except csv.Error:
        delim = ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delim)
    rows = [dict(r) for r in reader]
    cols = reader.fieldnames or []
    return list(cols), rows


def _parse_xml(content: bytes) -> tuple[List[str], List[dict]]:
    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        raise HTTPException(400, f"XML çözümlenemedi: {e}")
    # Find repeated leaf-ish elements
    items = list(root)
    if len(items) == 0:
        raise HTTPException(400, "XML içinde ürün öğesi bulunamadı")
    rows: List[dict] = []
    cols: List[str] = []
    for item in items:
        row = {}
        for child in item:
            tag = child.tag.split("}")[-1]
            row[tag] = (child.text or "").strip()
            if tag not in cols:
                cols.append(tag)
        # Also include attributes of item
        for k, v in item.attrib.items():
            if k not in row:
                row[k] = v
                if k not in cols:
                    cols.append(k)
        rows.append(row)
    return cols, rows


# --- Health / status ------------------------------------------------------
@api.get("/health")
def health():
    return {"status": "ok", "demo_mode": ai_service.is_demo_mode()}


# --- Dashboard ------------------------------------------------------------
@api.get("/dashboard/stats")
def dashboard_stats(db: Session = Depends(get_db)):
    total = db.query(Product).count()
    missing_desc = db.query(Product).filter(
        or_(Product.description.is_(None), Product.description == "")
    ).count()
    missing_price = db.query(Product).filter(Product.price.is_(None)).count()
    edited = db.query(Product).filter(Product.is_edited.is_(True)).count()
    last_import = db.query(Meta).filter(Meta.key == "last_import_at").first()
    activities = (
        db.query(Activity)
        .order_by(Activity.created_at.desc())
        .limit(10)
        .all()
    )
    return {
        "total_products": total,
        "missing_description": missing_desc,
        "missing_price": missing_price,
        "edited_products": edited,
        "last_import_at": last_import.value if last_import else None,
        "recent_activities": [
            {"id": a.id, "kind": a.kind, "message": a.message, "created_at": a.created_at.isoformat()}
            for a in activities
        ],
    }


# --- Products list --------------------------------------------------------
@api.get("/products")
def list_products(
    q: Optional[str] = None,
    category: Optional[str] = None,
    missing_desc: bool = False,
    missing_price: bool = False,
    in_stock: bool = False,
    edited: bool = False,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
):
    query = db.query(Product)
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
    total = query.count()
    items = (
        query.order_by(Product.updated_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [ProductOut.model_validate(p).model_dump(mode="json") for p in items],
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
    return ProductOut.model_validate(p).model_dump(mode="json")


@api.patch("/products/{pid}")
def update_product(pid: str, payload: ProductUpdate, db: Session = Depends(get_db)):
    p = db.get(Product, pid)
    if not p:
        raise HTTPException(404, "Ürün bulunamadı")
    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(p, k, v)
    p.is_edited = True
    _log_activity(db, "edit", f"Ürün güncellendi: {p.sku}")
    db.commit()
    db.refresh(p)
    return ProductOut.model_validate(p).model_dump(mode="json")


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
    return ProductOut.model_validate(p).model_dump(mode="json")


@api.post("/products/{pid}/improve")
async def improve_product(pid: str, payload: ImproveIn, db: Session = Depends(get_db)):
    p = db.get(Product, pid)
    if not p:
        raise HTTPException(404, "Ürün bulunamadı")
    if payload.kind in ("title", "both"):
        p.improved_name = await ai_service.improve_title(p.name, p.category)
    if payload.kind in ("description", "both"):
        p.improved_description = await ai_service.improve_description(
            p.improved_name or p.name, p.category, p.description
        )
    p.is_edited = True
    _log_activity(db, "edit", f"AI ile iyileştirildi ({payload.kind}): {p.sku}")
    db.commit()
    db.refresh(p)
    return ProductOut.model_validate(p).model_dump(mode="json")


# --- Import ---------------------------------------------------------------
@api.post("/import/preview")
async def import_preview(file: UploadFile = File(...)):
    content = await file.read()
    name = (file.filename or "").lower()
    if name.endswith(".xml"):
        cols, rows = _parse_xml(content)
    else:
        cols, rows = _parse_csv(content)
    return {"columns": cols, "sample": rows[:5], "total_rows": len(rows), "rows": rows}


@api.post("/import/commit")
def import_commit(payload: MappingIn, db: Session = Depends(get_db)):
    mapping = payload.mapping or {}
    if "sku" not in mapping or "name" not in mapping:
        raise HTTPException(400, "SKU ve Ürün Adı eşleştirmesi zorunludur")
    inserted = 0
    updated = 0
    for row in payload.rows:
        get = lambda field: row.get(mapping.get(field, ""), None) if mapping.get(field) else None  # noqa: E731
        sku = (get("sku") or "").strip()
        name_val = (get("name") or "").strip()
        if not sku or not name_val:
            continue
        existing = db.query(Product).filter(Product.sku == sku).first()
        data = {
            "sku": sku,
            "name": name_val,
            "description": get("description") or None,
            "category": get("category") or None,
            "price": _to_float(get("price")),
            "stock": _to_int(get("stock")) or 0,
            "image_url": get("image_url") or None,
            "product_url": get("product_url") or None,
        }
        if existing:
            for k, v in data.items():
                setattr(existing, k, v)
            updated += 1
        else:
            db.add(Product(**data))
            inserted += 1
    now = datetime.now(timezone.utc).isoformat()
    db.merge(Meta(key="last_import_at", value=now))
    _log_activity(db, "import", f"İçe aktarma tamamlandı: +{inserted} yeni, {updated} güncelleme")
    db.commit()
    return {"inserted": inserted, "updated": updated}


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


# --- Bulk operations ------------------------------------------------------
@api.post("/bulk/improve")
async def bulk_improve(payload: ImproveIn, ids_in: BulkIdsIn = None, db: Session = Depends(get_db)):  # unused
    raise HTTPException(400, "kullanılmıyor")


class BulkImproveIn(BulkIdsIn):
    kind: str = Field(..., pattern="^(title|description|both)$")


@api.post("/bulk/improve-products")
async def bulk_improve_products(payload: BulkImproveIn, db: Session = Depends(get_db)):
    products = db.query(Product).filter(Product.id.in_(payload.ids)).all()
    for p in products:
        if payload.kind in ("title", "both"):
            p.improved_name = await ai_service.improve_title(p.name, p.category)
        if payload.kind in ("description", "both"):
            p.improved_description = await ai_service.improve_description(
                p.improved_name or p.name, p.category, p.description
            )
        p.is_edited = True
    _log_activity(db, "bulk", f"Toplu iyileştirme ({payload.kind}): {len(products)} ürün")
    db.commit()
    return {"updated": len(products)}


@api.post("/bulk/category")
def bulk_category(payload: BulkCategoryIn, db: Session = Depends(get_db)):
    n = (
        db.query(Product)
        .filter(Product.id.in_(payload.ids))
        .update({"category": payload.category, "is_edited": True}, synchronize_session=False)
    )
    _log_activity(db, "bulk", f"Kategori atandı ({payload.category}): {n} ürün")
    db.commit()
    return {"updated": n}


@api.post("/bulk/price-percent")
def bulk_price_percent(payload: BulkPricePctIn, db: Session = Depends(get_db)):
    products = db.query(Product).filter(Product.id.in_(payload.ids)).all()
    n = 0
    factor = 1 + (payload.percent / 100.0)
    for p in products:
        if p.price is not None:
            p.price = round(p.price * factor, 2)
            p.is_edited = True
            n += 1
    _log_activity(db, "bulk", f"Fiyat %{payload.percent} güncellendi: {n} ürün")
    db.commit()
    return {"updated": n}


# --- Export ---------------------------------------------------------------
def _csv_response(products: List[Product]) -> StreamingResponse:
    buf = io.StringIO()
    buf.write("\ufeff")  # UTF-8 BOM for Excel Turkish support
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
    query = db.query(Product)
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
    products = query.all()
    _log_activity(db, "export", f"Filtrelenmiş ürünler dışa aktarıldı: {len(products)}")
    db.commit()
    return _csv_response(products)


# --- App wiring -----------------------------------------------------------
app.include_router(api)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)
