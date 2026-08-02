"""0002 merchant core: workflow status, quality, suggestions, revisions.

Preserves all Phase 1 data. Adds columns and 3 new tables. Sets sensible
defaults on existing rows.
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_merchant_core"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def _has_index(bind, table: str, name: str) -> bool:
    insp = sa.inspect(bind)
    if not insp.has_table(table):
        return False
    return any(ix["name"] == name for ix in insp.get_indexes(table))


def _has_column(bind, table: str, name: str) -> bool:
    insp = sa.inspect(bind)
    if not insp.has_table(table):
        return False
    return any(c["name"] == name for c in insp.get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()

    # 1) Product column additions (idempotent via batch_alter)
    with op.batch_alter_table("products") as batch:
        if not _has_column(bind, "products", "workflow_status"):
            batch.add_column(sa.Column(
                "workflow_status", sa.String(), nullable=False, server_default="imported",
            ))
        if not _has_column(bind, "products", "quality_score"):
            batch.add_column(sa.Column("quality_score", sa.Integer(), nullable=True))
        if not _has_column(bind, "products", "quality_analyzed_at"):
            batch.add_column(sa.Column("quality_analyzed_at", sa.DateTime(), nullable=True))
        if not _has_column(bind, "products", "active_suggestion_id"):
            batch.add_column(sa.Column("active_suggestion_id", sa.String(), nullable=True))

    # Ensure existing rows have workflow_status filled (SQLite server_default covers this).
    op.execute("UPDATE products SET workflow_status = 'imported' WHERE workflow_status IS NULL OR workflow_status = ''")

    if not _has_index(bind, "products", "ix_products_workflow_status"):
        op.create_index("ix_products_workflow_status", "products", ["workflow_status"])
    if not _has_index(bind, "products", "ix_products_quality_score"):
        op.create_index("ix_products_quality_score", "products", ["quality_score"])

    # 2) product_issues
    if not sa.inspect(bind).has_table("product_issues"):
        op.create_table(
            "product_issues",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("product_id", sa.String(),
                      sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
            sa.Column("issue_code", sa.String(), nullable=False),
            sa.Column("field_name", sa.String()),
            sa.Column("severity", sa.String(), nullable=False),
            sa.Column("message", sa.String(), nullable=False),
            sa.Column("recommendation", sa.String()),
            sa.Column("is_resolved", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("resolved_at", sa.DateTime()),
        )
        op.create_index("ix_issues_product_id", "product_issues", ["product_id"])
        op.create_index("ix_issues_severity", "product_issues", ["severity"])

    # 3) product_suggestions
    if not sa.inspect(bind).has_table("product_suggestions"):
        op.create_table(
            "product_suggestions",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("product_id", sa.String(),
                      sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
            sa.Column("suggested_name", sa.String()),
            sa.Column("suggested_description", sa.Text()),
            sa.Column("suggested_category", sa.String()),
            sa.Column("suggested_seo_title", sa.String()),
            sa.Column("suggested_meta_description", sa.String()),
            sa.Column("suggested_tags", sa.Text()),
            sa.Column("provider", sa.String(), nullable=False),
            sa.Column("model", sa.String()),
            sa.Column("suggestion_status", sa.String(), nullable=False, server_default="draft"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("approved_at", sa.DateTime()),
        )
        op.create_index("ix_suggestions_product_id", "product_suggestions", ["product_id"])

    # 4) product_revisions
    if not sa.inspect(bind).has_table("product_revisions"):
        op.create_table(
            "product_revisions",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("product_id", sa.String(),
                      sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
            sa.Column("action_type", sa.String(), nullable=False),
            sa.Column("source", sa.String(), nullable=False),
            sa.Column("before_snapshot", sa.Text()),
            sa.Column("after_snapshot", sa.Text()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_revisions_product_id", "product_revisions", ["product_id"])
        op.create_index("ix_revisions_created_at", "product_revisions", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_revisions_created_at", table_name="product_revisions")
    op.drop_index("ix_revisions_product_id", table_name="product_revisions")
    op.drop_table("product_revisions")

    op.drop_index("ix_suggestions_product_id", table_name="product_suggestions")
    op.drop_table("product_suggestions")

    op.drop_index("ix_issues_severity", table_name="product_issues")
    op.drop_index("ix_issues_product_id", table_name="product_issues")
    op.drop_table("product_issues")

    op.drop_index("ix_products_quality_score", table_name="products")
    op.drop_index("ix_products_workflow_status", table_name="products")
    with op.batch_alter_table("products") as batch:
        batch.drop_column("active_suggestion_id")
        batch.drop_column("quality_analyzed_at")
        batch.drop_column("quality_score")
        batch.drop_column("workflow_status")
