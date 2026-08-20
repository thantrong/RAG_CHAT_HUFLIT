"""Phân tích HTML của portal HUFLIT.

Trang danh sách: /News/Type/{type_id}?page={n} -> trích danh sách link chi tiết.
Trang chi tiết: /News/Detail/{id}/{slug}   -> trích tiêu đề, nội dung, file đính kèm.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from cawl.models import NewsItem

logger = logging.getLogger(__name__)


DETAIL_TITLE_SELECTOR = "a.title_topicdisplay"
DETAIL_BODY_SELECTOR = "div.divmain"
DETAIL_PARENT_SELECTOR = "div.col-md-9"
FILE_EXTS = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".rar")


class PortalParser:
    """Parser chuyên cho portal.huflit.edu.vn (ASP.NET MVC)."""

    def __init__(self, base_url: str, remove_selectors: list[str] | None = None):
        self.base_url = base_url
        self.remove_selectors = remove_selectors or ["nav", "footer", "script", "style"]


    def parse_detail_links(self, html: str, type_id: str) -> list[tuple[str, str]]:
        """Trích (url, source_id) của tất cả link News/Detail trong trang danh sách."""
        soup = BeautifulSoup(html, "lxml")
        links: list[tuple[str, str]] = []
        seen: set[str] = set()
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()

            m = re.match(r"^/News/Detail/(\d+)(?:/.*)?$", href)
            if not m:
                continue
            news_id = m.group(1)
            if news_id in seen:
                continue
            seen.add(news_id)
            links.append((urljoin(self.base_url, href), news_id))
        return links


    def parse_news_detail(self, html: str, url: str, news_id: str, type_id: str, category: str) -> NewsItem:
        """Phân tích trang chi tiết -> NewsItem."""
        soup = BeautifulSoup(html, "lxml")


        for sel in self.remove_selectors:
            for el in soup.select(sel):
                el.decompose()


        title_el = soup.select_one(DETAIL_TITLE_SELECTOR)
        title = title_el.get_text(" ", strip=True) if title_el else ""


        content_el = soup.select_one(DETAIL_BODY_SELECTOR)
        if content_el is None:
            parent = soup.select_one(DETAIL_PARENT_SELECTOR)
            content_el = parent if parent else soup.body


        if content_el is not None:
            self._strip_layout(content_el)


        content_html = str(content_el) if content_el else ""

        content_text = self._extract_text(content_el) if content_el else ""


        attachments = self._extract_attachments(content_el, url) if content_el else []


        published_at = self._extract_datetime(soup)

        return NewsItem(
            source_id=news_id,
            type_id=type_id,
            url=url,
            title=title,
            category=category,
            content_html=content_html,
            content_text=content_text,
            attachments=attachments,
            published_at=published_at,
        )

    def _strip_layout(self, el: Tag) -> None:
        """Loại bỏ các phần layout quanh nội dung bài viết trong vùng content."""

        for bg in el.select("div.bgtitle"):
            bg.decompose()

        for rem in el.select(".breadcrumb, .share, .toolbar, .social-links, .print, form"):
            rem.decompose()

    def _extract_attachments(self, content_el: Tag, page_url: str) -> list:
        """Tìm và mô tả các link file đính kèm trong nội dung."""
        from cawl.models import Attachment

        attachments: list[Attachment] = []
        for a in content_el.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith("#") or href.startswith("mailto:"):
                continue
            lower = href.lower()

            if not any(lower.endswith(ext) for ext in FILE_EXTS):
                continue
            abs_url = urljoin(self.base_url, href)
            filename = a.get_text(" ", strip=True) or Path(urlparse(abs_url).path).name or "file"
            ext = Path(urlparse(abs_url).path).suffix.lstrip(".").lower()
            attachments.append(
                Attachment(
                    url=abs_url,
                    filename=filename,
                    file_type=ext or "unknown",
                )
            )

        seen: set[str] = set()
        unique: list[Attachment] = []
        for att in attachments:
            if att.url in seen:
                continue
            seen.add(att.url)
            unique.append(att)
        return unique

    def _extract_datetime(self, soup: BeautifulSoup) -> datetime | None:
        """Trích ngày tháng bài đăng (nếu trang hiển thị)."""

        for text_node in soup.find_all(string=re.compile(r"\d{1,2}[/-]\d{1,2}[/-]\d{4}")):
            m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", str(text_node))
            if m:
                try:
                    return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
                except ValueError:
                    continue
        return None


    _BLOCK_TAGS = {
        "div", "p", "br", "li", "ul", "ol", "table", "tr", "td", "th",
        "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre",
        "section", "article", "header", "footer", "hr", "dt", "dd",
    }

    def _extract_text(self, el: Tag) -> str:
        """Trích text sạch: chỉ xuống dòng ở thẻ BLOCK, nối liền thẻ inline.

        Sửa lỗi cũ: get_text("\n") chèn xuống dòng giữa MỌI text node,
        kể cả giữa các thẻ <span> inline -> câu bị cắt vụn
        (vd: "Kế hoạch số" / "61" / "/KH-ĐNT" thay vì "Kế hoạch số 61/KH-ĐNT").
        """
        lines = self._walk(el)
        cleaned: list[str] = []
        for ln in lines:
            clean = re.sub(r"\s+", " ", ln).strip()
            if clean:
                cleaned.append(clean)
        return "\n".join(cleaned)

    def _walk(self, node) -> list[str]:
        """Duyệt cây: block -> mỗi phần riêng dòng; inline -> nối bằng space."""
        from bs4 import NavigableString

        if isinstance(node, NavigableString):
            t = str(node).strip()
            return [t] if t else []
        if not isinstance(node, Tag):
            return []

        tag_name = node.name.lower() if node.name else ""

        if tag_name in self._BLOCK_TAGS:
            parts: list[str] = []
            inline_buf: list[str] = []
            for child in node.children:
                if isinstance(child, Tag) and child.name and child.name.lower() in self._BLOCK_TAGS:
                    if inline_buf:
                        merged = " ".join(inline_buf).strip()
                        if merged:
                            parts.append(merged)
                        inline_buf = []
                    parts.extend(self._walk(child))
                else:
                    inline_buf.extend(self._walk(child))
            if inline_buf:
                merged = " ".join(inline_buf).strip()
                if merged:
                    parts.append(merged)
            return [p for p in parts if p]


        parts = []
        for child in node.children:
            parts.extend(self._walk(child))
        merged = " ".join(parts)
        return [merged] if merged.strip() else []
