from __future__ import annotations

import hashlib
import logging
import sqlite3
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlencode, urlparse, urlunparse

from cawl.config import CrawlerConfig

logger = logging.getLogger(__name__)


def canonicalize_url(url: str, drop_fragments: bool = True) -> str:
    """Chuẩn hoá URL để hash ổn định:
    - Loại bỏ fragment (#...)
    - Chuẩn hoá scheme/host về lowercase
    - Giữ thứ tự query deterministically
    """
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = parsed.path or "/"


    if drop_fragments:
        fragment = ""
    else:
        fragment = parsed.fragment


    if parsed.query:
        qs_list = [(k, v) for k, v in __import__("urllib.parse", fromlist=["parse_qsl"]).parse_qsl(parsed.query)]
        query = urlencode(sorted(qs_list), doseq=True)
    else:
        query = ""

    return urlunparse((scheme, netloc, path, parsed.params, query, fragment))


def url_hash(url: str, algorithm: str = "md5", length: Optional[int] = None) -> str:
    """Tạo mã định danh (hash) cho URL.

    canonicalize trước khi hash để cùng 1 trang -> cùng hash dù query khác thứ tự.
    """
    canon = canonicalize_url(url)
    try:
        h = hashlib.new(algorithm, canon.encode("utf-8")).hexdigest()
    except (ValueError, TypeError):
        logger.warning("Thuật toán hash '%s' không hợp lệ, dùng md5", algorithm)
        h = hashlib.md5(canon.encode("utf-8")).hexdigest()

    if length and length > 0:
        h = h[:length]
    return h


@dataclass
class QueuedUrl:
    """Một URL trong queue."""
    url: str
    depth: int = 0
    type_id: Optional[str] = None
    payload: dict = field(default_factory=dict)


class _MemoryQueue:
    """Queue trong bộ nhớ."""

    def __init__(self):
        self._q: deque[QueuedUrl] = deque()

    def push(self, item: QueuedUrl) -> None:
        self._q.append(item)

    def pop(self) -> Optional[QueuedUrl]:
        return self._q.popleft() if self._q else None

    def __len__(self) -> int:
        return len(self._q)

    def clear(self) -> None:
        self._q.clear()


class _SqliteQueue:
    """Queue lưu trong SQLite (persistent)."""

    def __init__(self, path: str):
        self._path = path
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL UNIQUE,
                depth INTEGER DEFAULT 0,
                type_id TEXT,
                payload TEXT DEFAULT '{}'
            )
            """
        )
        self._conn.commit()
        self._lock = threading.Lock()

    def push(self, item: QueuedUrl) -> None:
        import json
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO queue (url, depth, type_id, payload) VALUES (?, ?, ?, ?)",
                (item.url, item.depth, item.type_id, json.dumps(item.payload, ensure_ascii=False)),
            )
            self._conn.commit()

    def pop(self) -> Optional[QueuedUrl]:
        import json
        with self._lock:
            row = self._conn.execute(
                "SELECT url, depth, type_id, payload FROM queue ORDER BY id LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            self._conn.execute("DELETE FROM queue WHERE url = ?", (row[0],))
            self._conn.commit()
            return QueuedUrl(
                url=row[0],
                depth=int(row[1]),
                type_id=row[2],
                payload=json.loads(row[3]) if row[3] else {},
            )

    def __len__(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM queue").fetchone()[0]

    def clear(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM queue")
            self._conn.commit()

    def close(self) -> None:
        self._conn.close()


class _VisitedSet:
    """Tập hash URL đã xử lý.

    Hỗ trợ memory (set) hoặc sqlite (bảng visited bền vững).
    """

    def __init__(self, backend: str, sqlite_path: Optional[str] = None):
        self._backend = backend
        if backend == "sqlite" and sqlite_path:
            self._conn = sqlite3.connect(sqlite_path, check_same_thread=False)
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS visited (url_hash TEXT PRIMARY KEY, url TEXT NOT NULL)"
            )
            self._conn.commit()
            self._lock = threading.Lock()
        else:
            self._conn = None
            self._set: set[str] = set()
            self._lock = threading.Lock()

    def add(self, url_hash: str, url: str) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.execute(
                    "INSERT OR IGNORE INTO visited (url_hash, url) VALUES (?, ?)",
                    (url_hash, url),
                )
                self._conn.commit()
            else:
                self._set.add(url_hash)

    def contains(self, url_hash: str) -> bool:
        with self._lock:
            if self._conn is not None:
                row = self._conn.execute(
                    "SELECT 1 FROM visited WHERE url_hash = ?", (url_hash,)
                ).fetchone()
                return row is not None
            return url_hash in self._set

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()


class Frontier:
    """Frontier tổng hợp: queue + visited set + hash URL."""

    def __init__(self, config: CrawlerConfig):
        self.config = config
        self.hash_algorithm = config.hash_algorithm
        self.hash_length = config.hash_length


        if config.queue_backend == "sqlite":
            self._queue: _MemoryQueue | _SqliteQueue = _SqliteQueue(config.queue_path)

            self._visited = _VisitedSet("sqlite", config.queue_path)
        else:
            self._queue = _MemoryQueue()
            self._visited = _VisitedSet("memory")


    def hash_of(self, url: str) -> str:
        """Hash của URL theo config (canonicalize + băm)."""
        canon = canonicalize_url(url) if self.config.canonicalize else url
        return url_hash(canon, self.hash_algorithm, self.hash_length)

    def push(self, url: str, depth: int = 0, type_id: Optional[str] = None, payload: Optional[dict] = None) -> bool:
        """Thêm URL vào queue nếu chưa xử lý. Trả về True nếu thêm được."""
        h = self.hash_of(url)
        if self._visited.contains(h):
            return False
        self._queue.push(QueuedUrl(url=url, depth=depth, type_id=type_id, payload=payload or {}))
        return True

    def pop(self) -> Optional[QueuedUrl]:
        """Lấy URL kế tiếp trong queue."""
        return self._queue.pop()

    def mark_visited(self, url: str) -> str:
        """Đánh dấu URL đã xử lý. Trả về hash được tạo."""
        h = self.hash_of(url)
        self._visited.add(h, url)
        return h

    def is_visited(self, url: str) -> bool:
        return self._visited.contains(self.hash_of(url))

    def __len__(self) -> int:
        return len(self._queue)

    def clear(self) -> None:
        self._queue.clear()

    def close(self) -> None:
        if hasattr(self._queue, "close"):
            self._queue.close()
        self._visited.close()
