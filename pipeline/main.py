from __future__ import annotations

import argparse
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pipeline")


def main() -> None:
    p = argparse.ArgumentParser(description="RAG chat HUFLIT (LangChain)")
    p.add_argument("question", nargs="+", help="Câu hỏi của sinh viên")
    args = p.parse_args()
    question = " ".join(args.question)

    from pipeline.chain import RAGChain

    logger.info("Đang khởi tạo RAG chain...")
    rag = RAGChain()

    logger.info("Câu hỏi: %s", question)
    result = rag.ask(question)

    print("\n===== TRẢ LỜI =====")
    print(result["answer"])
    print("\n===== NGUỒN THAM KHẢO =====")
    for s in result["sources"]:
        line = f"[{s['index']}] {s['title']}"
        if s["category"]:
            line += f" ({s['category']})"
        if s["source_url"]:
            line += f"\n    {s['source_url']}"
        if s["referenced_by"]:
            line += f"\n    Tham chiếu bởi thông báo: {', '.join(s['referenced_by'])}"
        print(line)


if __name__ == "__main__":
    main()
