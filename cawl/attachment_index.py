from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

MANIFEST_NAME = "attachments_index.json"


def sha256_bytes(data: bytes) -> str:
    """Tính SHA256 (hex) của một khối bytes."""
    return hashlib.sha256(data).hexdigest()


class AttachmentIndex:
    """Bản đồ checksum(SHA256) -> bản ghi file duy nhất (dedup theo nội dung)."""

    def __init__(self, path_data: str | Path):
        self.root = Path(path_data)
        self.manifest_path = self.root / MANIFEST_NAME
        self._records: dict[str, dict] = {}
        self._load()


    def _load(self) -> None:
        if self.manifest_path.exists():
            try:
                data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._records = data
                logger.info("Đã nạp attachment index: %d nội dung", len(self._records))
            except Exception as e:
                logger.warning(
                    "Không đọc được manifest %s: %s — khởi tạo mới", self.manifest_path, e
                )
                self._records = {}
        else:
            self._records = {}

    def _save(self) -> None:
        """Ghi manifest an toàn (viết file tmp rồi rename)."""
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.manifest_path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(self._records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self.manifest_path)


    def get(self, checksum: str) -> Optional[dict]:
        """Trả về bản ghi nếu checksum đã có VÀ file còn trên đĩa.

        Trả về None nếu chưa có, hoặc file đã bị xoá (coi như cần lưu lại).
        """
        rec = self._records.get(checksum)
        if rec is None:
            return None
        lp = rec.get("local_path")
        if lp and Path(lp).exists():
            return rec
        logger.debug("Checksum có trong index nhưng file không còn trên đĩa: %s", checksum[:12])
        return None

    def put(
        self,
        checksum: str,
        local_path: str | Path,
        size_bytes: int,
        file_type: str,
        source_id: str,
        url: str,
    ) -> dict:
        """Tạo bản ghi mới cho một nội dung vừa lưu."""
        rec = {
            "checksum": checksum,
            "local_path": str(local_path),
            "size_bytes": int(size_bytes),
            "file_type": file_type,
            "urls": [url] if url else [],
            "referenced_by": [str(source_id)],
            "first_source_id": str(source_id),
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
        }
        self._records[checksum] = rec
        self._save()
        return rec

    def add_reference(self, checksum: str, source_id: str, url: str) -> Optional[dict]:
        """Đánh dấu một thông báo tham chiếu nội dung đã tồn tại.

        Thêm source_id vào referenced_by và url vào urls (không trùng lặp).
        """
        rec = self._records.get(checksum)
        if rec is None:
            return None
        refs = rec.setdefault("referenced_by", [])
        if str(source_id) not in refs:
            refs.append(str(source_id))
        urls = rec.setdefault("urls", [])
        if url and url not in urls:
            urls.append(url)
        self._save()
        return rec

    def __len__(self) -> int:
        return len(self._records)
