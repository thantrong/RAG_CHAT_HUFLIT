from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from ingestion.config import get_config
from ingestion.loader import CrawlDataLoader

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("clean_step")


def run_clean(limit: int | None = None) -> None:
    config = get_config()
    root = Path(config.path_data)
    cleaned_dir = root / "cleaned"


    if cleaned_dir.exists():
        shutil.rmtree(cleaned_dir)
        logger.info("Đã xoá thư mục cleaned cũ: %s", cleaned_dir)


    loader = CrawlDataLoader(root)
    docs = loader.load_all()
    if limit:
        docs = docs[:limit]
    logger.info("Đã đọc + làm sạch %d document", len(docs))


    now = datetime.now().isoformat()
    stats: dict[str, int] = {}
    for d in docs:
        sub = cleaned_dir / d.kind
        sub.mkdir(parents=True, exist_ok=True)
        payload = {
            "doc_id": d.doc_id,
            "kind": d.kind,
            "title": d.title,
            "content": d.content,
            "source_url": d.source_url,
            "category": d.category,
            "source_id": d.source_id,
            "referenced_by": d.referenced_by,
            "metadata": d.metadata,
            "cleaned_at": now,
        }
        out = sub / f"{d.doc_id}.json"
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        stats[d.kind] = stats.get(d.kind, 0) + 1


    manifest = {
        "created_at": now,
        "total_documents": len(docs),
        "by_kind": stats,
        "documents": [
            {
                "doc_id": d.doc_id,
                "kind": d.kind,
                "title": d.title,
                "category": d.category,
                "chars": len(d.content),
                "file": f"{d.kind}/{d.doc_id}.json",
            }
            for d in docs
        ],
    }
    (cleaned_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\n===== KẾT QUẢ LÀM SẠCH =====")
    print(f"Thư mục:   {cleaned_dir}")
    print(f"Tổng số:   {len(docs)} documents")
    for kind, n in sorted(stats.items()):
        print(f"  {kind:<12} {n:>5}")
    sizes = [len(d.content) for d in docs]
    if sizes:
        print(f"Độ dài:    min={min(sizes)}  max={max(sizes)}  avg={sum(sizes)//len(sizes)} chars")
    print(f"Manifest:  {cleaned_dir / 'manifest.json'}")
    print("\n👉 Mở thư mục cleaned/ để DUYỆT nội dung.")
    print("   Ưng rồi thì chạy:  python -m ingestion.main --clear")


def main() -> None:
    p = argparse.ArgumentParser(description="Bước làm sạch NLP: raw -> cleaned/")
    p.add_argument("--limit", type=int, default=None,
                   help="Giới hạn số document (mặc định: tất cả)")
    args = p.parse_args()
    run_clean(limit=args.limit)


if __name__ == "__main__":
    main()
