"""Bước làm sạch NLP: xử lý nội dung crawl trước khi chunking + embedding.

Pipeline (theo config/junk_phrases.yaml):
    1. Re-extract text từ content_html (sửa lỗi cắt vụn do <span> inline)
    2. Chuẩn hóa Unicode về NFC
    3. Thay ký tự đặc biệt (zero-width, nbsp, dash...) theo thư viện
    4. Xoá cụm từ rác inline (vui lòng xem tại đây, bấm vào để xem...)
    5. Xoá dòng rác (dòng chỉ chứa ký tự vô nghĩa)
    6. Gộp khoảng trắng/xuống dòng thừa, xoá dòng lặp

Sử dụng:
    from ingestion.cleaner import TextCleaner
    cleaner = TextCleaner()
    clean_text = cleaner.clean_html(html)      # từ HTML gốc
    clean_text = cleaner.clean_text(text)      # từ text có sẵn
"""

from __future__ import annotations

import logging
import os
import re
import unicodedata
from typing import Optional

import yaml
from bs4 import BeautifulSoup, NavigableString, Tag

logger = logging.getLogger(__name__)


BLOCK_TAGS = {
    "div", "p", "br", "li", "ul", "ol", "table", "tr", "td", "th",
    "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre",
    "section", "article", "header", "footer", "hr", "dt", "dd",
}


class TextCleaner:
    """Làm sạch text cho pipeline RAG."""

    def __init__(self, junk_config_path: Optional[str] = None):
        if junk_config_path is None:
            default_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "config",
            )
            junk_config_path = os.path.join(default_dir, "junk_phrases.yaml")

        with open(junk_config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}


        self._inline_patterns = [
            re.compile(re.escape(p), re.IGNORECASE)
            for p in raw.get("inline_patterns", [])
        ]
        self._line_patterns = [
            re.compile(p, re.IGNORECASE)
            for p in raw.get("line_patterns", [])
        ]

        self._char_map: dict[str, str] = {}
        for k, v in (raw.get("char_replacements") or {}).items():

            key = k.encode().decode("unicode_escape") if "\\u" in repr(k) else k
            val = v.encode().decode("unicode_escape") if v and "\\u" in repr(v) else (v or "")
            self._char_map[key] = val

        logger.info(
            "TextCleaner: %d inline patterns, %d line patterns, %d char replacements",
            len(self._inline_patterns), len(self._line_patterns), len(self._char_map),
        )


    def clean_html(self, html: str) -> str:
        """Trích text sạch từ HTML: chỉ xuống dòng ở thẻ block, nối liền thẻ inline."""
        if not html:
            return ""
        soup = BeautifulSoup(html, "lxml")

        for tag in soup.find_all(["script", "style", "nav", "footer", "noscript"]):
            tag.decompose()

        root = soup.body or soup
        lines = self._walk_block(root)
        text = "\n".join(lines)

        return self.clean_text(text)

    def _walk_block(self, node) -> list[str]:
        """Duyệt cây HTML, gom text theo cấu trúc block/inline."""
        if isinstance(node, NavigableString):
            t = str(node).strip()
            return [t] if t else []

        if not isinstance(node, Tag):
            return []

        tag_name = node.name.lower() if node.name else ""


        if tag_name in BLOCK_TAGS:
            parts: list[str] = []
            current_inline: list[str] = []

            for child in node.children:
                if isinstance(child, Tag) and child.name and child.name.lower() in BLOCK_TAGS:

                    if current_inline:
                        merged = " ".join(current_inline).strip()
                        if merged:
                            parts.append(merged)
                        current_inline = []

                    sub = self._walk_block(child)
                    parts.extend(sub)
                else:

                    sub = self._walk_block(child)
                    current_inline.extend(sub)

            if current_inline:
                merged = " ".join(current_inline).strip()
                if merged:
                    parts.append(merged)

            return [p for p in parts if p]


        parts = []
        for child in node.children:
            parts.extend(self._walk_block(child))
        merged = " ".join(parts)
        return [merged] if merged.strip() else []


    def clean_text(self, text: str) -> str:
        """Áp dụng toàn bộ bước làm sạch lên text."""
        if not text:
            return ""


        text = unicodedata.normalize("NFC", text)


        for char, repl in self._char_map.items():
            text = text.replace(char, repl)


        for pat in self._inline_patterns:
            text = pat.sub("", text)


        text = re.sub(r"[ \t]+/", "/", text)
        text = re.sub(r"/[ \t]+", "/", text)
        text = re.sub(r"(?<=\d)[ \t]+(?=\d)", "", text)


        lines = text.split("\n")
        cleaned_lines: list[str] = []
        seen: set[str] = set()

        for line in lines:

            line = re.sub(r"[ \t]+", " ", line).strip()
            if not line:
                continue


            if any(p.match(line) for p in self._line_patterns):
                continue


            if len(line) <= 3:
                if line in seen:
                    continue
                seen.add(line)

            cleaned_lines.append(line)


        result = "\n".join(cleaned_lines)
        result = re.sub(r"\n{3,}", "\n\n", result)
        return result.strip()
