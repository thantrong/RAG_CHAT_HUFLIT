from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import yaml

from settings import database_url, secret


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
class EmbeddingConfig:
    """Embedding model (config/embedding.yaml)."""
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
class RetrievalConfig:
    mode: str
    vector_top_k: int
    vector_score_threshold: float
    bm25_top_k: int
    fusion_method: str
    vector_weight: float
    bm25_weight: float
    final_top_k: int

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "RetrievalConfig":
        v = raw.get("vector", {})
        b = raw.get("bm25", {})
        f = raw.get("fusion", {})
        return cls(
            mode=raw.get("mode", "hybrid"),
            vector_top_k=int(v.get("top_k", 25)),
            vector_score_threshold=float(v.get("score_threshold", 0.25)),
            bm25_top_k=int(b.get("top_k", 15)),
            fusion_method=f.get("method", "weighted"),
            vector_weight=float(f.get("vector_weight", 0.65)),
            bm25_weight=float(f.get("bm25_weight", 0.35)),
            final_top_k=int(raw.get("final_top_k", 10)),
        )


@dataclass
class RerankerConfig:
    enabled: bool
    provider: str
    model: str
    candidate_count: int
    top_k: int
    batch_size: int
    api_key: str | None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "RerankerConfig":
        return cls(
            enabled=bool(raw.get("enabled", True)),
            provider=raw.get("provider", "voyage"),
            model=raw.get("model", "rerank-2.5-lite"),
            candidate_count=int(raw.get("candidate_count", 20)),
            top_k=int(raw.get("top_k", 6)),
            batch_size=int(raw.get("batch_size", 8)),
            api_key=secret("VOYAGE_API_KEY"),
        )


@dataclass
class LLMConfig:
    provider: str
    model: str
    endpoint: str
    temperature: float
    top_p: float
    max_output_tokens: int
    timeout: int
    max_retries: int
    system_prompt: str
    api_key: str | None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "LLMConfig":
        return cls(
            provider=raw.get("provider", "google"),
            model=raw.get("model", "gemini-3.5-flash-lite"),
            endpoint=raw.get(
                "endpoint",
                "https://generativelanguage.googleapis.com/v1beta/openai",
            ),
            temperature=float(raw.get("temperature", 0.2)),
            top_p=float(raw.get("top_p", 0.9)),
            max_output_tokens=int(raw.get("max_output_tokens", 2048)),
            timeout=int(raw.get("timeout", 60)),
            max_retries=int(raw.get("max_retries", 3)),
            system_prompt=raw.get("system_prompt", ""),
            api_key=secret("GOOGLE_API_KEY"),
        )


@dataclass
class AppConfig:
    """Cấu hình tầng ứng dụng (config/app.yaml)."""
    api_host: str
    api_port: int
    cors_allow_origins: list[str]
    ui_api_url: str
    ui_request_timeout: int
    ui_health_check_timeout: int
    ui_suggestions: list[str]

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "AppConfig":
        api = raw.get("api", {})
        ui = raw.get("ui", {})
        return cls(
            api_host=api.get("host", "0.0.0.0"),
            api_port=int(api.get("port", 8000)),
            cors_allow_origins=list(api.get("cors_allow_origins", ["*"])),
            ui_api_url=ui.get("api_url", "http://127.0.0.1:8000"),
            ui_request_timeout=int(ui.get("request_timeout", 120)),
            ui_health_check_timeout=int(ui.get("health_check_timeout", 5)),
            ui_suggestions=list(ui.get("suggestions", [])),
        )


@dataclass
class PipelineConfig:
    database: DatabaseConfig
    embedding: EmbeddingConfig
    retrieval: RetrievalConfig
    reranker: RerankerConfig
    llm: LLMConfig
    app: AppConfig

    @classmethod
    def from_dir(cls, cfg_dir: str) -> "PipelineConfig":
        def load(name: str) -> dict[str, Any]:
            with open(os.path.join(cfg_dir, name), "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return cls(
            database=DatabaseConfig.from_dict(load("database.yaml")),
            embedding=EmbeddingConfig.from_dict(load("embedding.yaml")),
            retrieval=RetrievalConfig.from_dict(load("retrieval.yaml")),
            reranker=RerankerConfig.from_dict(load("reranker.yaml")),
            llm=LLMConfig.from_dict(load("llm.yaml")),
            app=AppConfig.from_dict(load("app.yaml")),
        )


_CONFIG: PipelineConfig | None = None


def get_config() -> PipelineConfig:
    global _CONFIG
    if _CONFIG is None:
        default_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config",
        )
        cfg_dir = os.environ.get("PIPELINE_CONFIG_DIR", default_dir)
        _CONFIG = PipelineConfig.from_dir(cfg_dir)
    return _CONFIG
