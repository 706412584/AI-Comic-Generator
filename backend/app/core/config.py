import os
import sys

from pydantic_settings import BaseSettings

from app.core.paths import data_dir


def _default_database_url() -> str:
    # 桌面端 / 打包运行时把数据库放到统一数据目录；开发模式保持原有相对路径行为。
    if os.environ.get("COMIC_APP_DATA_DIR") or hasattr(sys, "_MEIPASS"):
        db_path = data_dir() / "comic_app.db"
        return f"sqlite:///{db_path.as_posix()}"
    return "sqlite:///./comic_app.db"


class Settings(BaseSettings):
    PROJECT_NAME: str = "AI Comic Generator"
    API_V1_STR: str = "/api/v1"
    DATABASE_URL: str = _default_database_url()

    class Config:
        env_file = ".env"

settings = Settings()
