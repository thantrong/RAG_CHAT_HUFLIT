"""Các dataclass biểu diễn dữ liệu crawl."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class NewsItem:
    """Một bài viết/ thông báo trên portal."""
    source_id: str
    type_id: str
    url: str
    title: str
    category: str
    content_html: str
    content_text: str
    attachments: list["Attachment"] = field(default_factory=list)
    published_at: Optional[datetime] = None
    crawled_at: datetime = field(default_factory=datetime.utcnow)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Chuyển đổi thành dict để lưu JSON."""
        return {
            "source_id": self.source_id,
            "type_id": self.type_id,
            "url": self.url,
            "title": self.title,
            "category": self.category,
            "content_html": self.content_html,
            "content_text": self.content_text,
            "attachments": [a.to_dict() for a in self.attachments],
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "crawled_at": self.crawled_at.isoformat(),
            "metadata": self.metadata,
        }


@dataclass
class Attachment:
    """File đính kèm của một bài viết (pdf/docx/...)."""
    url: str
    filename: str
    file_type: str
    local_path: Optional[str] = None
    content_text: Optional[str] = None
    size_bytes: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "filename": self.filename,
            "file_type": self.file_type,
            "local_path": self.local_path,
            "content_text": self.content_text,
            "size_bytes": self.size_bytes,
        }
