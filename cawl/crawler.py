from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

from cawl.attachment_index import AttachmentIndex, sha256_bytes
from cawl.config import CrawlConfig, _slugify, get_config
from cawl.extractor import extract_text_from_file
from cawl.fetcher import Fetcher
from cawl.frontier import Frontier, QueuedUrl
from cawl.models import Attachment, NewsItem
from cawl.parser import PortalParser
from cawl.storage import Storage

logger = logging.getLogger(__name__)


class Crawler:
    """Crawler dùng frontier (queue + hash URL)."""

    def __init__(self, config: Optional[CrawlConfig] = None):
        self.config = config or get_config()
        self.fetcher = Fetcher(self.config)
        self.parser = PortalParser(
            base_url=self.config.base_url,
            remove_selectors=self.config.content.remove,
        )
        self.storage = Storage(path_data=self.config.path_data)

        self.attachment_index = AttachmentIndex(self.config.path_data)

        self.frontier: Optional[Frontier] = None

        self.categories: dict[str, str] = {}
        for nt in self.config.news_types:
            self.categories[nt.id] = nt.display


    def _push_seed(self, frontier: Frontier, nt) -> None:
        """Push URL danh sách của một loại tin vào frontier."""
        url = urljoin(
            self.config.base_url,
            self.config.news_type_path.format(type_id=nt.id),
        )
        frontier.push(
            url,
            depth=0,
            type_id=nt.id,
            payload={"kind": "list"},
        )
        logger.debug("Seed %s (type=%s) -> %s", url, nt.id, "pushed")


    def _classify_url(self, url: str) -> str:
        """Trả về 'list' | 'detail' | 'other' dựa trên pattern URL."""
        m = re.search(r"/News/Type/(\d+)", url)
        if m:
            return "list"
        m = re.search(r"/News/Detail/(\d+)", url)
        if m:
            return "detail"
        return "other"


    def _process_url(self, item: QueuedUrl) -> int:
        """Xử lý 1 URL từ queue. Trả về số URL mới được push thêm."""
        url = item.url
        kind = self._classify_url(url)


        if self.config.crawler.politeness_delay > 0:
            time.sleep(self.config.crawler.politeness_delay)

        try:
            html = self.fetcher.fetch_text(url)
        except Exception as e:
            logger.warning("Lỗi tải %s: %s", url, e)
            return 0

        new_pushed = 0

        if kind == "list":

            m = re.search(r"/News/Type/(\d+)", url)
            type_id = m.group(1) if m else item.type_id
            links = self.parser.parse_detail_links(html, type_id)
            for detail_url, news_id in links:

                pushed = self.frontier.push(
                    detail_url,
                    depth=item.depth + 1,
                    type_id=type_id,
                    payload={"kind": "detail", "news_id": news_id},
                )
                if pushed:
                    new_pushed += 1


            if links:
                m = re.search(r"[?&]page=(\d+)", url)
                current_page = int(m.group(1)) if m else 1
                next_url = url
                if m:
                    next_url = url.replace(f"page={current_page}", f"page={current_page + 1}")
                else:
                    sep = "&" if "?" in url else "?"
                    next_url = f"{url}{sep}page=2"

                push_ok = self.frontier.push(
                    next_url,
                    depth=item.depth,
                    type_id=type_id,
                    payload={"kind": "list"},
                )
                if push_ok:
                    new_pushed += 1

        elif kind == "detail":

            m = re.search(r"/News/Detail/(\d+)", url)
            news_id = m.group(1) if m else item.payload.get("news_id", "")
            category = self.categories.get(item.type_id or "", item.type_id or "type")
            item_news = self.parser.parse_news_detail(html, url, news_id, item.type_id or "", category)
            if item_news:

                self._process_attachments(item_news)
                cat_slug = _slugify(category)
                self.storage.save_news(item_news, cat_slug)
                logger.info("Đã lưu: [%s] %s", category, item_news.title[:60])
            else:
                logger.warning("Không parse được: %s", url)

        else:

            logger.debug("Bỏ qua URL khác: %s", url)

        return new_pushed


    _CONTENT_TYPE_EXT = {
        "application/pdf": "pdf",
        "application/msword": "doc",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
        "application/vnd.ms-excel": "xls",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
        "application/zip": "zip",
        "application/x-zip-compressed": "zip",
        "text/plain": "txt",
    }
    _KNOWN_EXTS = ("pdf", "doc", "docx", "xls", "xlsx", "zip", "txt")
    _TEXT_EXTRACTABLE = ("pdf", "docx")

    def _process_attachments(self, item: NewsItem) -> None:
        """Tải + dedup + trích text cho toàn bộ attachments của một bài viết.

        Dedup theo CHECKSUM (SHA256) nội dung:
        - Luôn tải file về (bytes trong bộ nhớ) rồi tính SHA256.
        - Checksum ĐÃ TỒN TẠI -> file trùng: KHÔNG lưu mới, chỉ đánh dấu
          thông báo hiện tại tham chiếu bản gốc (referenced_by).
        - Checksum MỚI -> lưu file ra đĩa + tạo bản ghi index.

        Kết quả: một nội dung = một file trên đĩa, được nhiều thông báo
        tham chiếu (many-to-one). Không còn file trùng trên đĩa.
        """
        if not self.config.download_attachments:
            return
        for att in item.attachments:
            try:
                self._process_one_attachment(item, att)
            except Exception as e:
                logger.warning("  Attachment %s thất bại: %s", att.url, e)

    def _process_one_attachment(self, item: NewsItem, att: Attachment) -> None:
        """Xử lý một attachment duy nhất: tải -> dedup checksum -> trích text."""

        resp = self.fetcher.session.get(att.url, timeout=self.config.request_timeout)
        resp.raise_for_status()
        content = resp.content
        content_type = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()


        ext = self._resolve_ext(att, content_type)


        checksum = sha256_bytes(content)
        existing = self.attachment_index.get(checksum)

        if existing is not None:

            self.attachment_index.add_reference(checksum, item.source_id, att.url)
            local = Path(existing["local_path"])
            att.local_path = str(local)
            att.size_bytes = existing.get("size_bytes") or len(content)
            if existing.get("file_type") and att.file_type == "unknown":
                att.file_type = existing["file_type"]
            logger.info("  Attachment %s: TRÙNG nội dung (sha256=%s...) -> tham chiếu %s",
                        att.filename, checksum[:12], local.name)
        else:

            local = self.storage.save_attachment(att, item.source_id, content)
            att.local_path = str(local)
            att.size_bytes = len(content)
            self.attachment_index.put(
                checksum=checksum,
                local_path=local,
                size_bytes=len(content),
                file_type=att.file_type,
                source_id=item.source_id,
                url=att.url,
            )
            logger.info("  Attachment %s (%s): %d KB -> lưu mới",
                        att.filename, ext or "?", len(content) // 1024)


        self._maybe_extract_text(att)

    def _resolve_ext(self, att: Attachment, content_type: str) -> str:
        """Xác định extension từ file_type hoặc Content-Type; chuẩn hoá filename."""
        ext = att.file_type if att.file_type != "unknown" else self._CONTENT_TYPE_EXT.get(content_type, "")
        if not ext or ext not in self._KNOWN_EXTS:
            ext = self._CONTENT_TYPE_EXT.get(content_type, "")
        if ext and att.file_type == "unknown":
            att.file_type = ext
        if ext and not att.filename.lower().endswith(f".{ext}"):
            att.filename = f"{Path(att.filename).stem}.{ext}"
        return ext

    def _maybe_extract_text(self, att: Attachment) -> None:
        """Trích text nếu là loại file hỗ trợ (pdf/docx) và file tồn tại."""
        if att.file_type not in self._TEXT_EXTRACTABLE:
            return
        if not att.local_path or not Path(att.local_path).exists():
            return
        att.content_text = extract_text_from_file(Path(att.local_path))


    def _drain_queue(self, frontier: Frontier, limit: int, stats: dict, cap: Optional[int]) -> int:
        """Xử lý hết queue hiện tại (hoặc tới giới hạn cap). Trả về số URL đã xử lý.

        Giữ cơ chế queue + hash: pop, skip nếu visited, xử lý, mark visited.
        """
        processed = 0
        while cap is None or processed < cap:
            if limit and processed >= limit:
                logger.info("Đạt giới hạn %d trang (toàn cục), dừng.", limit)
                return processed

            item = frontier.pop()
            if item is None:
                logger.info("Queue rỗng, hoàn tất loại tìm.")
                return processed


            if frontier.is_visited(item.url):
                stats["skipped"] += 1
                continue

            new_links = self._process_url(item)
            frontier.mark_visited(item.url)

            processed += 1
            kind = self._classify_url(item.url)
            if kind == "list":
                stats["list_pages"] += 1
            elif kind == "detail":
                stats["detail_pages"] += 1
            stats["new_links"] += new_links
            stats["processed"] = stats.get("processed", 0) + 1

            if processed % 10 == 0:
                logger.info("  Đã xử lý %d URL loại này, queue còn %d", processed, len(frontier))

        return processed

    def run(self, max_pages_limit: Optional[int] = None) -> dict:
        """Chạy crawl theo từng loại tin (type) tuần tự, mỗi loại dùng frontier riêng.

        Đảm bảo mỗi category đều được crawl đầy đủ (không bị 1 loại chiếm hết tài nguyên).
        max_pages_limit: giới hạn tổng số URL xử lý (None = config.max_pages_total).
        """
        limit = max_pages_limit if max_pages_limit is not None else self.config.crawler.max_pages_total
        if limit == 0:
            limit = None

        stats = {"processed": 0, "skipped": 0, "list_pages": 0, "detail_pages": 0, "new_links": 0}
        by_category: dict[str, dict] = {}


        for nt in self.config.news_types:
            if limit is not None and stats["processed"] >= limit:
                logger.info("Đạt giới hạn %d trang (toàn cục), dừng.", limit)
                break

            category = self.categories.get(nt.id, nt.display)

            frontier = Frontier(self.config.crawler)
            self.frontier = frontier
            self._push_seed(frontier, nt)
            logger.info("=== Crawl loại: %s (id=%s) ===", nt.display, nt.id)

            before = stats["processed"]
            remaining = (limit - stats["processed"]) if limit is not None else None
            self._drain_queue(frontier, limit, stats, cap=remaining)

            frontier.close()
            n_done = stats["processed"] - before
            by_category[category] = {"processed": n_done, "ok": n_done}
            logger.info("Hoàn tất loại %s: %d URL", category, n_done)

        stats["by_category"] = by_category
        stats["total_news_saved"] = self.storage.count_news()
        return stats
