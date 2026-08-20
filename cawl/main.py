"""CLI để chạy crawl dữ liệu portal HUFLIT bằng cơ chế frontier (queue + hash).

Mỗi lần chạy LUÔN bắt đầu với một queue MỚI: file queue sqlite cũ (nếu có)
được xoá tự động trước khi crawl, nên không cần cờ --clear-queue.

Ví dụ:
    python -m cawl.main                       # crawl theo các loại tin trong config
    python -m cawl.main --limit 50            # giới hạn tổng số URL xử lý
"""

from __future__ import annotations

import argparse
import json
import logging
import os

from cawl.config import get_config
from cawl.crawler import Crawler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("crawl")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Crawl portal HUFLIT cho RAG chat sinh viên (frontier)")
    p.add_argument("--limit", type=int, default=None,
                   help="Giới hạn tổng số URL xử lý (mặc định: dùng config.max_pages_total)")
    p.add_argument("--list-types", action="store_true",
                   help="In danh sách loại tin trong config rồi thoát")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    config = get_config()

    if args.list_types:
        print("=== Các loại tin trong config ===")
        for nt in config.news_types:
            print(f"  id={nt.id:<6} display={nt.display:<25} slug={nt.slug}")
        return


    queue_path = config.crawler.queue_path
    if os.path.exists(queue_path):
        os.remove(queue_path)
        logger.info("Đã xoá queue cũ, bắt đầu với queue mới: %s", queue_path)

    crawler = Crawler(config)
    stats = crawler.run(max_pages_limit=args.limit)

    print("\n===== KẾT QUẢ CRAWL (frontier) =====")
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
