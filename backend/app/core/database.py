from sqlalchemy import inspect, text
from sqlmodel import SQLModel, create_engine, Session
from app.core.config import settings

connect_args = {}
if "sqlite" in settings.DATABASE_URL:
    connect_args["check_same_thread"] = False

engine = create_engine(settings.DATABASE_URL, echo=False, connect_args=connect_args)

SQLITE_COLUMN_DEFAULTS = {
    "project": {
        "current_chapter_id": "INTEGER",
        "workflow_mode": "VARCHAR DEFAULT 'comic'",
        "memory_enabled": "BOOLEAN DEFAULT 1",
        "setting_mode": "VARCHAR DEFAULT 'basic'",
        "outline_enabled": "BOOLEAN DEFAULT 1",
    },
    "character": {
        "summary": "VARCHAR",
        "aliases": "JSON DEFAULT '[]'",
        "status": "VARCHAR DEFAULT 'active'",
        "default_outfit_id": "INTEGER",
    },
    "storyboarditem": {
        "chapter_id": "INTEGER",
        "selected_outfits": "JSON DEFAULT '{}'",
        "status": "VARCHAR DEFAULT 'draft'",
        "prompt_cache": "VARCHAR",
    },
    "chapter": {
        "preview_text": "VARCHAR",
        "current_location": "VARCHAR",
        "current_time": "VARCHAR",
        "pov_character": "VARCHAR",
        "word_count": "INTEGER DEFAULT 0",
        "source_chapter_id": "INTEGER",
        "adaptation_mode": "VARCHAR DEFAULT 'adapt'",
        "source_context_note": "VARCHAR",
        "metadata": "JSON DEFAULT '{}'",
    },
    "memoryentry": {
        "memory_type": "VARCHAR DEFAULT 'event'",
        "chapter_id": "INTEGER",
        "character_id": "INTEGER",
    },
    "chapterversion": {
        "preview_text": "VARCHAR",
        "word_count": "INTEGER DEFAULT 0",
    },
    "task": {
        "scope_type": "VARCHAR",
        "scope_id": "VARCHAR",
        "input_payload": "JSON DEFAULT '{}'",
        "retry_count": "INTEGER DEFAULT 0",
        "retry_of_task_id": "VARCHAR",
    },
    "sourceimport": {
        "summary_layers": "JSON DEFAULT '{}'",
    },
    "sourcechapter": {
        "analysis_status": "VARCHAR DEFAULT 'pending'",
        "analysis_error": "VARCHAR",
        "analysis_attempts": "INTEGER DEFAULT 0",
    },
    "modelconfig": {
        "is_default": "BOOLEAN DEFAULT 0",
    },
}

def _ensure_sqlite_columns():
    if not settings.DATABASE_URL.startswith("sqlite"):
        return

    inspector = inspect(engine)
    with engine.begin() as connection:
        for table_name, columns in SQLITE_COLUMN_DEFAULTS.items():
            if not inspector.has_table(table_name):
                continue
            existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
            for column_name, column_sql in columns.items():
                if column_name not in existing_columns:
                    connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}"))

def _alembic_config():
    from pathlib import Path

    from alembic.config import Config

    backend_root = Path(__file__).resolve().parents[2]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))
    config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
    return config


def init_db():
    """通过 Alembic 管理 schema。

    - 全新数据库：直接 upgrade 到 head 建表。
    - 引入 Alembic 前的旧数据库（有业务表但无 alembic_version）：先按旧逻辑补齐
      表和列（一次性过渡），再 stamp 到 head。
    - 已纳管数据库：正常 upgrade。
    """
    from alembic import command

    config = _alembic_config()
    inspector = inspect(engine)
    has_business_tables = inspector.has_table("project")
    has_alembic_version = inspector.has_table("alembic_version")

    if has_business_tables and not has_alembic_version:
        SQLModel.metadata.create_all(engine)
        _ensure_sqlite_columns()
        command.stamp(config, "head")
        return

    command.upgrade(config, "head")

def get_session():
    with Session(engine) as session:
        yield session
