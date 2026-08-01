"""initial schema with unique SKU

Revision ID: 0001_initial
Revises:
Create Date: 2026-02-01

Idempotent: works whether the tables already exist (created by
Base.metadata.create_all in an earlier build) or not. Also deduplicates
existing SKUs (trims whitespace + suffixes exact duplicates) so the new
UNIQUE constraint can be safely applied without deleting user data.
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def _has_table(bind, name: str) -> bool:
    return sa.inspect(bind).has_table(name)


def _has_index(bind, table: str, name: str) -> bool:
    if not _has_table(bind, table):
        return False
    return any(ix["name"] == name for ix in sa.inspect(bind).get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()

    if not _has_table(bind, "products"):
        op.create_table(
            "products",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("sku", sa.String(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("improved_name", sa.String()),
            sa.Column("description", sa.Text()),
            sa.Column("improved_description", sa.Text()),
            sa.Column("category", sa.String()),
            sa.Column("price", sa.Float()),
            sa.Column("stock", sa.Integer(), server_default="0"),
            sa.Column("image_url", sa.String()),
            sa.Column("product_url", sa.String()),
            sa.Column("is_edited", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("sku", name="uq_products_sku"),
        )
        op.create_index("ix_products_category", "products", ["category"])
    else:
        # Dedup + normalize whitespace, then add unique constraint if missing.
        conn = op.get_bind()
        conn.exec_driver_sql("UPDATE products SET sku = TRIM(sku) WHERE sku <> TRIM(sku)")
        # If duplicates exist, keep the newest and suffix older ones.
        dup_rows = conn.exec_driver_sql(
            "SELECT sku FROM products GROUP BY sku HAVING COUNT(*) > 1"
        ).fetchall()
        for (sku,) in dup_rows:
            rows = conn.exec_driver_sql(
                "SELECT id FROM products WHERE sku = ? ORDER BY updated_at DESC",
                (sku,),
            ).fetchall()
            for i, (pid,) in enumerate(rows[1:], start=1):
                conn.exec_driver_sql(
                    "UPDATE products SET sku = ? WHERE id = ?",
                    (f"{sku}__dup{i}", pid),
                )
        if not _has_index(bind, "products", "uq_products_sku"):
            with op.batch_alter_table("products") as batch:
                batch.create_unique_constraint("uq_products_sku", ["sku"])
        if not _has_index(bind, "products", "ix_products_category"):
            op.create_index("ix_products_category", "products", ["category"])

    if not _has_table(bind, "activities"):
        op.create_table(
            "activities",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("kind", sa.String(), nullable=False),
            sa.Column("message", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )

    if not _has_table(bind, "meta"):
        op.create_table(
            "meta",
            sa.Column("key", sa.String(), primary_key=True),
            sa.Column("value", sa.String()),
        )


def downgrade() -> None:
    op.drop_table("meta")
    op.drop_table("activities")
    op.drop_index("ix_products_category", table_name="products")
    op.drop_table("products")
