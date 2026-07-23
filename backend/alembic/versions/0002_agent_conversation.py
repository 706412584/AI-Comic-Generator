"""Agent conversation tables for workbench chat

Revision ID: 0002_agent_conversation
Revises: 0001_baseline
Create Date: 2026-07-23

"""
from alembic import op
import sqlalchemy as sa  # noqa: F401

revision = "0002_agent_conversation"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlmodel import SQLModel

    import app.models.models  # noqa: F401

    bind = op.get_bind()
    # Idempotent: only create missing agent conversation tables
    SQLModel.metadata.create_all(
        bind=bind,
        tables=[
            SQLModel.metadata.tables["agentconversation"],
            SQLModel.metadata.tables["agentmessage"],
        ],
    )


def downgrade() -> None:
    op.drop_table("agentmessage")
    op.drop_table("agentconversation")
