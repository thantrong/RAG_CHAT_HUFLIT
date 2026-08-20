from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Document:
    """Một tài liệu gốc (bài viết news hoặc file đính kèm PDF/DOCX)."""
    doc_id: str
    kind: str
    title: str
    content: str
    source_url: Optional[str] = None
    category: Optional[str] = None
    source_id: Optional[str] = None
    referenced_by: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
