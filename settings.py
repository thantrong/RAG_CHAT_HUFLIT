from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_DIR = Path(os.environ.get("RAG_CONFIG_DIR", PROJECT_ROOT / "config"))


load_dotenv(PROJECT_ROOT / ".env")

_YAML_CACHE: dict[str, dict[str, Any]] = {}


def load_yaml(name: str) -> dict[str, Any]:
    """Đọc (và cache) một file yaml trong thư mục config/."""
    if name not in _YAML_CACHE:
        path = CONFIG_DIR / name
        if not path.exists():
            raise FileNotFoundError(f"Thiếu file cấu hình: {path}")
        with open(path, "r", encoding="utf-8") as f:
            _YAML_CACHE[name] = yaml.safe_load(f) or {}
    return _YAML_CACHE[name]


def secret(name: str, default: str | None = None) -> str | None:
    """Đọc một secret từ biến môi trường (.env)."""
    return os.environ.get(name, default)


def database_url() -> str:
    """Dựng URL kết nối PostgreSQL từ database.yaml + secret DB_PASSWORD."""
    db = load_yaml("database.yaml")["postgres"]
    password = secret("DB_PASSWORD", "")
    return (
        f"postgresql://{db['username']}:{password}"
        f"@{db['host']}:{db['port']}/{db['database']}"
    )
