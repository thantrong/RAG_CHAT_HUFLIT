"""Enricher: nạp nội dung các file bên ngoài (SharePoint/Google Drive) đã tải.

Đọc download_log.json, trích text từ các file tải OK (pdf/docx),
tạo Document cho mỗi file. Được gọi từ loader để bổ sung vào pipeline.

Sử dụng:
    from ingestion.enricher import ExternalFileLoader
    loader = ExternalFileLoader(path_data)
    for doc in loader.iter_documents(): ...
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from pathlib import Path
from typing import Iterator, Optional

from ingestion.cleaner import TextCleaner
from ingestion.models import Document

logger = logging.getLogger(__name__)


from ingestion.config import get_config as _get_ingestion_config

EXTRACT_TIMEOUT = _get_ingestion_config().extraction.timeout

_executor = ThreadPoolExecutor(max_workers=1)


def _extract_sync(path: Path) -> Optional[str]:
    from cawl.extractor import extract_text_from_file
    return extract_text_from_file(path)


def extract_with_timeout(path: Path, timeout: int = EXTRACT_TIMEOUT) -> Optional[str]:
    """Trích text từ file với timeout (thread-based). Trả về None nếu lỗi/quá giờ."""
    future = _executor.submit(_extract_sync, path)
    try:
        return future.result(timeout=timeout)
    except FutureTimeout:
        logger.warning("Trích text quá %ds, bỏ qua: %s", timeout, path.name)
        future.cancel()
        return None
    except Exception as e:
        logger.warning("Lỗi trích text %s: %s", path.name, e)
        return None


class ExternalFileLoader:
    """Đọc các file bên ngoài đã tải (external_files/) thành Document."""

    def __init__(self, path_data: str | Path):
        self.root = Path(path_data)
        self.ext_dir = self.root / "external_files"
        self.log_path = self.ext_dir / "download_log.json"
        self.cleaner = TextCleaner()

    def iter_documents(self) -> Iterator[Document]:
        """Sinh Document cho mỗi file ngoài tải thành công."""
        if not self.log_path.exists():
            logger.info("Không có download_log.json, bỏ qua external files")
            return

        try:
            log = json.loads(self.log_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("Không đọc được download_log.json: %s", e)
            return


        ok_files = [
            (kind, url, info)
            for kind in ("sharepoint", "google_drive")
            for url, info in (log.get(kind) or {}).items()
            if info.get("status") == "ok"
        ]
        total = len(ok_files)
        logger.info("Bắt đầu trích text từ %d file ngoài...", total)

        count = 0
        done = 0
        for kind, url, info in ok_files:
            done += 1
            fname = info.get("file", "")
            fpath = self.ext_dir / fname
            if not fpath.exists():
                logger.warning("[%d/%d] File trong log nhưng mất: %s", done, total, fname)
                continue


            text = extract_with_timeout(fpath)
            if not text or not text.strip():
                logger.warning("[%d/%d] Không trích được text (hoặc timeout): %s", done, total, fname)
                continue

            text = self.cleaner.clean_text(text)
            logger.info("[%d/%d] OK %s (%d chars)", done, total, fname, len(text))


            doc_id = f"ext-{fpath.stem[:40]}"
            yield Document(
                doc_id=doc_id,
                kind="external",
                title=info.get("title", fpath.stem),
                content=text.strip(),
                source_url=url,
                category=info.get("category"),
                source_id=str(info.get("source_id", "")),
                metadata={
                    "origin": kind,
                    "file_name": fname,
                    "size_bytes": info.get("size"),
                },
            )
            count += 1

        logger.info("ExternalFileLoader: %d documents từ file ngoài", count)
