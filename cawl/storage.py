from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from cawl.models import Attachment, NewsItem

logger = logging.getLogger(__name__)


class Storage:
    """Lưu NewsItem thành JSON theo cấu trúc:

    path_data/
      news/
        {category_slug}/
          {source_id}.json
      attachments/
        {source_id}/
          {filename}
    """

    def __init__(self, path_data: str | Path):
        self.root = Path(path_data)
        self.news_dir = self.root / "news"
        self.attachments_dir = self.root / "attachments"

    def save_news(self, item: NewsItem, category_slug: str) -> Path:
        """Lưu một bài viết dạng JSON. Trả về đường dẫn file đã ghi."""
        cat_dir = self.news_dir / category_slug
        cat_dir.mkdir(parents=True, exist_ok=True)
        out = cat_dir / f"{item.source_id}.json"
        out.write_text(
            json.dumps(item.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return out

    def save_attachment(self, attachment: Attachment, source_id: str, content: bytes) -> Path:
        """Lưu file đính kèm binary. Trả về đường dẫn file đã ghi."""
        att_dir = self.attachments_dir / str(source_id)
        att_dir.mkdir(parents=True, exist_ok=True)

        safe_name = Path(attachment.filename).name or "file"
        out = att_dir / safe_name
        out.write_bytes(content)
        return out

    def count_news(self) -> int:
        """Đếm tổng số bài viết đã lưu."""
        return sum(1 for _ in self.news_dir.rglob("*.json")) if self.news_dir.exists() else 0
