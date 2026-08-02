"""Verify Alembic migration 0003 preserves existing data and adds two tables."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _run_alembic(target: str, sqlite_path: str) -> None:
    env = os.environ.copy()
    env["SQLITE_PATH"] = sqlite_path
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade" if target != "0002_merchant_core" or target == "0002_merchant_core" else "downgrade", target],
        cwd=str(BACKEND_DIR), env=env, capture_output=True, text=True,
    )
    # Fall through -- caller checks state directly.


def _alembic(cmd: list, sqlite_path: str):
    env = os.environ.copy()
    env["SQLITE_PATH"] = sqlite_path
    r = subprocess.run(
        [sys.executable, "-m", "alembic"] + cmd,
        cwd=str(BACKEND_DIR), env=env, capture_output=True, text=True,
    )
    assert r.returncode == 0, (
        f"alembic {' '.join(cmd)} failed:\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}"
    )
    return r


@pytest.fixture()
def sqlite_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        yield path
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _seed_pre_0003(engine):
    """Insert one row into each table that existed before 0003."""
    now = datetime.now(timezone.utc).isoformat()
    pid = str(uuid.uuid4())
    sid = str(uuid.uuid4())
    iid = str(uuid.uuid4())
    rid = str(uuid.uuid4())
    aid = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO products (id, sku, name, is_edited, workflow_status,
                                  created_at, updated_at)
            VALUES (:id, :sku, :name, 0, 'imported', :now, :now)
        """), {"id": pid, "sku": "MIG-1", "name": "Migration ürünü", "now": now})
        conn.execute(text("""
            INSERT INTO activities (id, kind, message, created_at)
            VALUES (:id, 'import', 'seed', :now)
        """), {"id": aid, "now": now})
        conn.execute(text("""
            INSERT INTO product_issues (id, product_id, issue_code, severity,
                                        message, is_resolved, created_at)
            VALUES (:id, :pid, 'missing_desc', 'warning', 'x', 0, :now)
        """), {"id": iid, "pid": pid, "now": now})
        conn.execute(text("""
            INSERT INTO product_suggestions (
                id, product_id, provider, suggestion_status,
                created_at, updated_at
            ) VALUES (:id, :pid, 'demo', 'draft', :now, :now)
        """), {"id": sid, "pid": pid, "now": now})
        conn.execute(text("""
            INSERT INTO product_revisions (id, product_id, action_type, source,
                                           created_at)
            VALUES (:id, :pid, 'analyze', 'quality_engine', :now)
        """), {"id": rid, "pid": pid, "now": now})
    return {"product_id": pid, "suggestion_id": sid}


def _counts(engine) -> dict:
    tables = ("products", "activities", "product_issues",
              "product_suggestions", "product_revisions")
    with engine.connect() as conn:
        return {t: conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar() for t in tables}


def test_upgrade_preserves_data_and_adds_tables(sqlite_path):
    _alembic(["upgrade", "0002_merchant_core"], sqlite_path)
    engine = create_engine(f"sqlite:///{sqlite_path}")
    seed = _seed_pre_0003(engine)
    before = _counts(engine)

    _alembic(["upgrade", "head"], sqlite_path)

    insp = inspect(engine)
    assert insp.has_table("product_publications")
    assert insp.has_table("category_mappings")

    after = _counts(engine)
    assert before == after, "Existing table counts changed during upgrade"

    # Indexes / uniques exist.
    pp_ix = {ix["name"] for ix in insp.get_indexes("product_publications")}
    assert {"ix_product_publications_product_id",
            "ix_product_publications_channel",
            "ix_product_publications_status"}.issubset(pp_ix)

    cm_ix = {ix["name"] for ix in insp.get_indexes("category_mappings")}
    assert {"ix_category_mappings_channel",
            "ix_category_mappings_local_category"}.issubset(cm_ix)

    pp_uniques = {u["name"] for u in insp.get_unique_constraints("product_publications")}
    cm_uniques = {u["name"] for u in insp.get_unique_constraints("category_mappings")}
    assert "uq_product_publications_product_channel" in pp_uniques
    assert "uq_category_mappings_channel_local_category" in cm_uniques

    # ProductPublication has FK to products
    fks = insp.get_foreign_keys("product_publications")
    fk_targets = {(fk["referred_table"], tuple(fk["referred_columns"])) for fk in fks}
    assert ("products", ("id",)) in fk_targets

    # Unique constraints actually enforced.
    now = datetime.now(timezone.utc).isoformat()
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO category_mappings (id, channel, local_category,
                                           external_category_id, external_category_name,
                                           created_at, updated_at)
            VALUES ('m1', 'woocommerce', 'X', 5, 'Y', :now, :now)
        """), {"now": now})
    with engine.begin() as conn:
        try:
            conn.execute(text("""
                INSERT INTO category_mappings (id, channel, local_category,
                                               external_category_id, external_category_name,
                                               created_at, updated_at)
                VALUES ('m2', 'woocommerce', 'X', 6, 'Z', :now, :now)
            """), {"now": now})
            uniq_violation = False
        except Exception:
            uniq_violation = True
    assert uniq_violation, "channel+local_category unique constraint not enforced"


def test_downgrade_only_removes_woocommerce_tables(sqlite_path):
    _alembic(["upgrade", "0002_merchant_core"], sqlite_path)
    engine = create_engine(f"sqlite:///{sqlite_path}")
    _seed_pre_0003(engine)
    before = _counts(engine)

    _alembic(["upgrade", "head"], sqlite_path)
    _alembic(["downgrade", "0002_merchant_core"], sqlite_path)

    insp = inspect(engine)
    assert not insp.has_table("product_publications")
    assert not insp.has_table("category_mappings")

    after = _counts(engine)
    assert before == after, "Merchant Core counts changed during downgrade"

    # Re-upgrade works.
    _alembic(["upgrade", "head"], sqlite_path)
    insp2 = inspect(engine)
    assert insp2.has_table("product_publications")
    assert insp2.has_table("category_mappings")
