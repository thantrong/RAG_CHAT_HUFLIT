"""Cấu hình tập trung của toàn project.

QUY ƯỚC:
    - Mọi THAM SỐ cấu hình nằm trong config/*.yaml (mỗi module một file tương ứng).
    - Mọi SECRET (API key, mật khẩu) nằm trong .env — KHÔNG lưu trong yaml.

Các file yaml:
    database.yaml   -> kết nối PostgreSQL + pgvector (collection, distance...)
    embedding.yaml  -> embedding model (provider, model, dim, batch)
    llm.yaml        -> LLM (model, endpoint, temperature, system_prompt...)
    retrieval.yaml  -> truy xuất hybrid (vector/bm25/fusion)
    reranker.yaml   -> rerank
    chunking.yaml   -> tách chunk
    app.yaml        -> FastAPI + Streamlit (port, url, timeout, suggestions)
    crawl.yaml      -> crawler + extraction timeout + external download
    junk_phrases.yaml -> thư viện từ rác

Các secret trong .env:
    DB_PASSWORD, VOYAGE_API_KEY, GOOGLE_API_KEY, HUFLIT_USERNAME, HUFLIT_PASSWORD
"""

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
