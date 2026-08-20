from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import yaml


@dataclass
class RetryConfig:
    enabled: bool
    max_attempts: int
    backoff_seconds: float


@dataclass
class ContentConfig:
    remove: list[str]


@dataclass
class CrawlerConfig:
    enabled: bool
    queue_backend: str
    queue_path: str
    hash_algorithm: str
    hash_length: int
    canonicalize: bool
    politeness_delay: float
    max_pages_total: int


@dataclass
class NewsType:
    id: str
    display: str

    @property
    def slug(self) -> str:
        return _slugify(self.display)


@dataclass
class CrawlConfig:
    base_url: str
    path_data: str
    crawl_interval_hours: int
    max_concurrency: int
    request_timeout: int
    retry: RetryConfig
    content: ContentConfig
    download_attachments: bool
    allowed_types: list[str]
    crawler: CrawlerConfig
    news_types: list[NewsType]


    news_type_path: str
    news_detail_path: str
    page_param: str

    @classmethod
    def from_yaml(cls, path: str | os.PathLike[str]) -> "CrawlConfig":
        with open(path, "r", encoding="utf-8") as f:
            raw: dict[str, Any] = yaml.safe_load(f) or {}

        retry_raw = raw.get("retry", {})
        content_raw = raw.get("content", {})
        crawler_raw = raw.get("crawler", {})
        news_types_raw = raw.get("news_types", [])


        def req(key: str) -> Any:
            if key not in raw:
                raise ValueError(f"Thiếu cấu hình bắt buộc '{key}' trong {path}")
            return raw[key]


        news_type_path = raw.get("news_type_path", "/News/Type/{type_id}")
        news_detail_path = raw.get("news_detail_path", "/News/Detail/{news_id}/{slug}")
        page_param = raw.get("page_param", "page")

        return cls(
            base_url=req("base_url"),
            path_data=req("Path_Data"),
            crawl_interval_hours=int(raw.get("crawl_interval_hours", 6)),
            max_concurrency=int(raw.get("max_concurrency", 5)),
            request_timeout=int(raw.get("request_timeout", 20)),
            retry=RetryConfig(
                enabled=bool(retry_raw.get("enabled", True)),
                max_attempts=int(retry_raw.get("max_attempts", 3)),
                backoff_seconds=float(retry_raw.get("backoff_seconds", 2.0)),
            ),
            content=ContentConfig(
                remove=list(content_raw.get("remove", ["nav", "footer", "script", "style"])),
            ),
            download_attachments=bool(raw.get("download_attachments", True)),
            allowed_types=list(raw.get("allowed_types", ["html", "pdf", "docx"])),
            crawler=CrawlerConfig(
                enabled=bool(crawler_raw.get("enabled", True)),
                queue_backend=crawler_raw.get("queue_backend", "sqlite"),
                queue_path=str(crawler_raw.get("queue_path", "crawler_queue.sqlite")),
                hash_algorithm=crawler_raw.get("hash_algorithm", "md5"),
                hash_length=int(crawler_raw.get("hash_length", 16)),
                canonicalize=bool(crawler_raw.get("canonicalize", True)),
                politeness_delay=float(crawler_raw.get("politeness_delay", 0.5)),
                max_pages_total=int(crawler_raw.get("max_pages_total", 0)),
            ),
            news_types=[
                NewsType(id=str(nt.get("id", "")), display=nt.get("display", str(nt.get("id", ""))))
                for nt in news_types_raw
            ],
            news_type_path=news_type_path,
            news_detail_path=news_detail_path,
            page_param=page_param,
        )

    @property
    def urljoin(self) -> str:
        """Đảm bảo base_url kết thúc bằng '/'."""
        return self.base_url.rstrip("/") + "/"


def _slugify(text: str, max_len: int = 40) -> str:
    import re
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    text = text.strip("-")
    return text[:max_len] or "uncategorized"


_CONFIG: CrawlConfig | None = None


def get_config() -> CrawlConfig:
    """Lấy cấu hình crawl (singleton). Xuất phát từ config/crawl.yaml."""
    global _CONFIG
    if _CONFIG is None:
        default_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config",
            "crawl.yaml",
        )
        config_path = os.environ.get("CRAWL_CONFIG", default_path)
        _CONFIG = CrawlConfig.from_yaml(config_path)
    return _CONFIG
