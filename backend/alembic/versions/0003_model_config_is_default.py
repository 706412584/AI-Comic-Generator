"""Add is_default to modelconfig

Revision ID: 0003_model_config_is_default
Revises: 0002_agent_conversation
Create Date: 2026-07-25
"""

from alembic import op
import sqlalchemy as sa

revision = "0003_model_config_is_default"
down_revision = "0002_agent_conversation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("modelconfig"):
        return
    columns = {column["name"] for column in inspector.get_columns("modelconfig")}
    if "is_default" not in columns:
        op.add_column(
            "modelconfig",
            sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        )

    # 每个 model_type 把 id 最小的启用配置标为默认（若尚无默认）
    for model_type in ("text", "image"):
        bind.execute(
            sa.text(
                """
                UPDATE modelconfig
                SET is_default = 1
                WHERE id = (
                    SELECT id FROM modelconfig
                    WHERE model_type = :model_type AND is_active = 1
                    ORDER BY id ASC
                    LIMIT 1
                )
                AND NOT EXISTS (
                    SELECT 1 FROM modelconfig
                    WHERE model_type = :model_type AND is_default = 1
                )
                """
            ),
            {"model_type": model_type},
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("modelconfig"):
        return
    columns = {column["name"] for column in inspector.get_columns("modelconfig")}
    if "is_default" in columns:
        op.drop_column("modelconfig", "is_default")
