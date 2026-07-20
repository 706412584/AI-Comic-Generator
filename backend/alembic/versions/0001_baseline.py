"""Baseline schema

以当前 SQLModel metadata 作为初始 schema。
已存在的旧数据库（在引入 Alembic 之前创建）由 init_db() 补齐列后 stamp 到本版本；
全新数据库直接由本迁移建表。

Revision ID: 0001_baseline
Revises:
Create Date: 2026-07-20

"""
from alembic import op
import sqlalchemy as sa  # noqa: F401

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlmodel import SQLModel

    import app.models.models  # noqa: F401

    bind = op.get_bind()
    SQLModel.metadata.create_all(bind=bind)


def downgrade() -> None:
    from sqlmodel import SQLModel

    import app.models.models  # noqa: F401

    bind = op.get_bind()
    SQLModel.metadata.drop_all(bind=bind)
