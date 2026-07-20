"""统一解析应用的数据目录。

优先级：
1. 环境变量 COMIC_APP_DATA_DIR（桌面端 Electron 壳会指向系统用户数据目录）；
2. PyInstaller 打包运行时，使用可执行文件旁边的 data 目录；
3. 开发模式下使用 backend 根目录（保持原有行为）。
"""

import os
import sys
from functools import lru_cache
from pathlib import Path


def backend_root() -> Path:
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def data_dir() -> Path:
    env_dir = os.environ.get("COMIC_APP_DATA_DIR")
    if env_dir:
        path = Path(env_dir)
    elif hasattr(sys, "_MEIPASS"):
        path = Path(sys.executable).resolve().parent / "data"
    else:
        path = backend_root()
    path.mkdir(parents=True, exist_ok=True)
    return path


def static_dir() -> Path:
    path = data_dir() / "static"
    path.mkdir(parents=True, exist_ok=True)
    return path
