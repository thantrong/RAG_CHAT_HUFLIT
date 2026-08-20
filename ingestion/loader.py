from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Iterator

from ingestion.cleaner import TextCleaner
from ingestion.enricher import ExternalFileLoader
from ingestion.models import Document

logger = logging.getLogger(__name__)


class CrawlDataLoader:
    """Đọc toàn bộ dữ liệu crawl thành danh sách Document (đã làm sạch)."""

    def __init__(self, path_data: str | Path):
        self.root = Path(path_data)
        self.news_dir = self.root / "news"
        self.index_path = self.root / "attachments_index.json"
        self.cleaner = TextCleaner()
        self.external_loader = ExternalFileLoader(path_data)


    def iter_documents(self) -> Iterator[Document]:
        """Sinh ra toàn bộ Document: news -> attachments -> external files."""
        yield from self._iter_news()
        yield from self._iter_attachments()
        yield from self.external_loader.iter_documents()

    def load_all(self) -> list[Document]:
        return list(self.iter_documents())


    def _iter_news(self) -> Iterator[Document]:
        """Đọc từng file news JSON -> Document."""
        if not self.news_dir.exists():
            logger.warning("Thư mục news không tồn tại: %s", self.news_dir)
            return
        for jf in sorted(self.news_dir.rglob("*.json")):
            try:
                raw = json.loads(jf.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning("Bỏ qua file lỗi %s: %s", jf, e)
                continue


            html = raw.get("content_html") or ""
            if html:
                content = self.cleaner.clean_html(html)
            else:
                content = self.cleaner.clean_text(raw.get("content_text") or "")
            content = content.strip()
            if not content:
                logger.debug("Bỏ qua bài không có nội dung: %s", jf.name)
                continue

            yield Document(
                doc_id=f"news-{raw.get('source_id', jf.stem)}",
                kind="news",
                title=(raw.get("title") or "").strip(),
                content=content,
                source_url=raw.get("url"),
                category=raw.get("category"),
                source_id=str(raw.get("source_id", "")),
                metadata={
                    "type_id": raw.get("type_id"),
                    "published_at": raw.get("published_at"),
                    "crawled_at": raw.get("crawled_at"),
                },
            )


    def _iter_attachments(self) -> Iterator[Document]:
        """Đọc attachment index -> Document cho mỗi nội dung duy nhất.

        Chỉ đọc các file pdf/docx có thể trích text. Text được trích từ file
        trên đĩa (dùng extractor của tầng crawl để tránh trùng logic).
        """
        if not self.index_path.exists():
            logger.info("Không có attachment index: %s", self.index_path)
            return

        try:
            index = json.loads(self.index_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("Không đọc được attachment index: %s", e)
            return


        from cawl.extractor import extract_text_from_file

        for checksum, rec in index.items():
            local = Path(rec.get("local_path", ""))
            if not local.exists():
                logger.warning("Attachment trong index nhưng file mất: %s", checksum[:12])
                continue
            if rec.get("file_type") not in ("pdf", "docx"):
                logger.debug("Bỏ qua attachment không trích được text: %s", local.name)
                continue

            text = extract_text_from_file(local)
            if not text or not text.strip():
                logger.warning("Attachment không trích được text: %s", local.name)
                continue

            text = self.cleaner.clean_text(text)

            yield Document(
                doc_id=f"att-{checksum[:12]}",
                kind="attachment",
                title=local.stem,
                content=text.strip(),
                source_url=(rec.get("urls") or [None])[0],
                source_id=rec.get("first_source_id"),
                referenced_by=list(rec.get("referenced_by", [])),
                metadata={
                    "checksum": checksum,
                    "file_type": rec.get("file_type"),
                    "size_bytes": rec.get("size_bytes"),
                },
            )


class CleanedDataLoader:
    """Đọc dữ liệu ĐÃ LÀM SẠCH từ thư mục cleaned/ -> Document.

    Dùng cho ingestion.main (bước embed): chỉ đọc từ TẦNG 2, không đụng raw.
    Mỗi file cleaned/{kind}/{doc_id}.json -> 1 Document, giữ nguyên doc_id.
    """

    def __init__(self, path_data: str | Path):
        self.root = Path(path_data)
        self.cleaned_dir = self.root / "cleaned"

    def iter_documents(self) -> Iterator[Document]:
        if not self.cleaned_dir.exists():
            logger.warning(
                "Thư mục cleaned/ chưa tồn tại: %s. "
                "Hãy chạy trước: python -m ingestion.clean_step",
                self.cleaned_dir,
            )
            return
        for jf in sorted(self.cleaned_dir.rglob("*.json")):
            if jf.name == "manifest.json":
                continue
            try:
                raw = json.loads(jf.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning("Bỏ qua file cleaned lỗi %s: %s", jf, e)
                continue
            content = (raw.get("content") or "").strip()
            if not content:
                logger.debug("Bỏ qua cleaned doc rỗng: %s", jf.name)
                continue
            yield Document(
                doc_id=raw.get("doc_id", jf.stem),
                kind=raw.get("kind", "unknown"),
                title=(raw.get("title") or "").strip(),
                content=content,
                source_url=raw.get("source_url"),
                category=raw.get("category"),
                source_id=str(raw.get("source_id") or ""),
                referenced_by=list(raw.get("referenced_by") or []),
                metadata=raw.get("metadata") or {},
            )

    def load_all(self) -> list[Document]:
        return list(self.iter_documents())
