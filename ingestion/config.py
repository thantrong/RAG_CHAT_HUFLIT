from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import yaml

from settings import database_url, secret


@dataclass
class ChunkingConfig:
    strategy: str
    chunk_size: int
    chunk_overlap: int
    separators: list[str]
    min_chunk_size: int
    max_chunk_size: int
    preserve_headings: bool
    preserve_lists: bool

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ChunkingConfig":
        return cls(
            strategy=raw.get("strategy", "recursive"),
            chunk_size=int(raw.get("chunk_size", 1000)),
            chunk_overlap=int(raw.get("chunk_overlap", 120)),
            separators=list(raw.get("separators", ["\n\n", "\n", ". ", " "])),
            min_chunk_size=int(raw.get("min_chunk_size", 150)),
            max_chunk_size=int(raw.get("max_chunk_size", 1200)),
            preserve_headings=bool(raw.get("preserve_headings", True)),
            preserve_lists=bool(raw.get("preserve_lists", True)),
        )


@dataclass
class EmbeddingConfig:
    provider: str
    model: str
    dim: int
    batch_size: int
    api_key: str | None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "EmbeddingConfig":
        return cls(
            provider=raw.get("provider", "voyage"),
            model=raw.get("model", "voyage-4"),
            dim=int(raw.get("dim", 1024)),
            batch_size=int(raw.get("batch_size", 16)),
            api_key=secret("VOYAGE_API_KEY"),
        )


@dataclass
class DatabaseConfig:
    """Kết nối PostgreSQL + pgvector (config/database.yaml)."""
    url: str
    collection_name: str
    distance_strategy: str
    use_jsonb: bool

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "DatabaseConfig":
        v = raw.get("vector", {})
        return cls(
            url=database_url(),
            collection_name=v.get("collection_name", "student_rag"),
            distance_strategy=v.get("distance_strategy", "cosine"),
            use_jsonb=bool(v.get("use_jsonb", True)),
        )


@dataclass
class ExtractionConfig:
    """Trích xuất text từ file (mục extraction trong crawl.yaml)."""
    timeout: int

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ExtractionConfig":
        return cls(timeout=int(raw.get("timeout", 60)))


@dataclass
class IngestionConfig:
    path_data: str
    chunking: ChunkingConfig
    embedding: EmbeddingConfig
    database: DatabaseConfig
    extraction: ExtractionConfig

    @classmethod
    def from_yaml(cls, chunking_path: str, crawl_path: str,
                  embedding_path: str, database_path: str) -> "IngestionConfig":
        def load(p: str) -> dict[str, Any]:
            with open(p, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}

        chunk_raw = load(chunking_path)
        crawl_raw = load(crawl_path)
        emb_raw = load(embedding_path)
        db_raw = load(database_path)

        path_data = crawl_raw.get("Path_Data")
        if not path_data:
            raise ValueError(f"Thiếu 'Path_Data' trong {crawl_path}")

        return cls(
            path_data=str(path_data),
            chunking=ChunkingConfig.from_dict(chunk_raw),
            embedding=EmbeddingConfig.from_dict(emb_raw),
            database=DatabaseConfig.from_dict(db_raw),
            extraction=ExtractionConfig.from_dict(crawl_raw.get("extraction", {})),
        )


_CONFIG: IngestionConfig | None = None


def _config_dir() -> str:
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config",
    )


def get_config() -> IngestionConfig:
    """Lấy cấu hình ingestion (singleton)."""
    global _CONFIG
    if _CONFIG is None:
        cfg_dir = os.environ.get("INGESTION_CONFIG_DIR", _config_dir())
        _CONFIG = IngestionConfig.from_yaml(
            chunking_path=os.path.join(cfg_dir, "chunking.yaml"),
            crawl_path=os.path.join(cfg_dir, "crawl.yaml"),
            embedding_path=os.path.join(cfg_dir, "embedding.yaml"),
            database_path=os.path.join(cfg_dir, "database.yaml"),
        )
    return _CONFIG
