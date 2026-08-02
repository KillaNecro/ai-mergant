"""0003 WooCommerce integration: product_publications + category_mappings.

Additive-only: creates two new tables plus their indexes and unique
constraints. Existing tables (products, activities, meta, product_issues,
product_suggestions, product_revisions) and their data are left untouched.
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_woocommerce_integration"
down_revision = "0002_merchant_core"
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

    # --- product_publications ---------------------------------------------
    if not _has_table(bind, "product_publications"):
        op.create_table(
            "product_publications",
            sa.Column("id", sa.String(), primary_key=True, nullable=False),
            sa.Column(
                "product_id",
                sa.String(),
                sa.ForeignKey("products.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("channel", sa.String(), nullable=False, server_default="woocommerce"),
            sa.Column("external_product_id", sa.String(), nullable=True),
            sa.Column("external_url", sa.String(), nullable=True),
            sa.Column(
                "publication_status", sa.String(), nullable=False, server_default="pending"
            ),
            sa.Column("payload_snapshot", sa.Text(), nullable=True),
            sa.Column("response_snapshot", sa.Text(), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("last_success_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint(
                "product_id", "channel", name="uq_product_publications_product_channel"
            ),
        )
    if not _has_index(bind, "product_publications", "ix_product_publications_product_id"):
        op.create_index(
            "ix_product_publications_product_id", "product_publications", ["product_id"]
        )
    if not _has_index(bind, "product_publications", "ix_product_publications_channel"):
        op.create_index(
            "ix_product_publications_channel", "product_publications", ["channel"]
        )
    if not _has_index(bind, "product_publications", "ix_product_publications_status"):
        op.create_index(
            "ix_product_publications_status",
            "product_publications",
            ["publication_status"],
        )

    # --- category_mappings ------------------------------------------------
    if not _has_table(bind, "category_mappings"):
        op.create_table(
            "category_mappings",
            sa.Column("id", sa.String(), primary_key=True, nullable=False),
            sa.Column("channel", sa.String(), nullable=False, server_default="woocommerce"),
            sa.Column("local_category", sa.String(), nullable=False),
            sa.Column("external_category_id", sa.Integer(), nullable=False),
            sa.Column("external_category_name", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "channel",
                "local_category",
                name="uq_category_mappings_channel_local_category",
            ),
        )
    if not _has_index(bind, "category_mappings", "ix_category_mappings_channel"):
        op.create_index("ix_category_mappings_channel", "category_mappings", ["channel"])
    if not _has_index(
        bind, "category_mappings", "ix_category_mappings_local_category"
    ):
        op.create_index(
            "ix_category_mappings_local_category", "category_mappings", ["local_category"]
        )


def downgrade() -> None:
    bind = op.get_bind()

    if _has_index(bind, "category_mappings", "ix_category_mappings_local_category"):
        op.drop_index("ix_category_mappings_local_category", table_name="category_mappings")
    if _has_index(bind, "category_mappings", "ix_category_mappings_channel"):
        op.drop_index("ix_category_mappings_channel", table_name="category_mappings")
    if _has_table(bind, "category_mappings"):
        op.drop_table("category_mappings")

    if _has_index(bind, "product_publications", "ix_product_publications_status"):
        op.drop_index("ix_product_publications_status", table_name="product_publications")
    if _has_index(bind, "product_publications", "ix_product_publications_channel"):
        op.drop_index("ix_product_publications_channel", table_name="product_publications")
    if _has_index(bind, "product_publications", "ix_product_publications_product_id"):
        op.drop_index(
            "ix_product_publications_product_id", table_name="product_publications"
        )
    if _has_table(bind, "product_publications"):
        op.drop_table("product_publications")
