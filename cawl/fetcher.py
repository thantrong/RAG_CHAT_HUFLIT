"""Tải nội dung từ web với retry và session dùng chung."""

from __future__ import annotations

import logging
import time
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from cawl.config import CrawlConfig, RetryConfig

logger = logging.getLogger(__name__)


class Fetcher:
    """Wrapper quanh requests với retry, timeout và User-Agent."""

    def __init__(self, config: CrawlConfig):
        self.config = config
        self.session = self._build_session()

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0 Safari/537.36"
                ),
                "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
            }
        )
        retry_cfg = self.config.retry
        if retry_cfg.enabled:
            retries = Retry(
                total=retry_cfg.max_attempts - 1,
                connect=retry_cfg.max_attempts - 1,
                read=retry_cfg.max_attempts - 1,
                backoff_factor=retry_cfg.backoff_seconds,
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["GET", "HEAD"],
            )
            adapter = HTTPAdapter(max_retries=retries, pool_connections=10, pool_maxsize=10)
            session.mount("http://", adapter)
            session.mount("https://", adapter)
        return session

    def fetch_bytes(self, url: str, timeout: Optional[int] = None) -> bytes:
        """Tải nội dung binary từ URL. Thất bại thì nâng HTTPError."""
        timeout = timeout or self.config.request_timeout
        resp = self.session.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.content

    def fetch_text(
        self,
        url: str,
        encoding: str = "utf-8",
        timeout: Optional[int] = None,
    ) -> str:
        """Tải nội dung text từ URL."""
        content = self.fetch_bytes(url, timeout=timeout)
        for enc in (encoding, "utf-8", "utf-8-sig", "latin-1"):
            try:
                return content.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
        return content.decode("utf-8", errors="replace")
