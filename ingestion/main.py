from __future__ import annotations

import argparse
import logging

from langchain_core.documents import Document as LCDocument
from langchain_postgres import PGVector
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_voyageai import VoyageAIEmbeddings

from ingestion.config import get_config
from ingestion.loader import CleanedDataLoader

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ingestion")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Embed (tầng 3): cleaned/ -> chunk -> embed -> PGVector")
    p.add_argument("--limit", type=int, default=None,
                   help="Giới hạn số document xử lý (mặc định: tất cả)")
    p.add_argument("--dry-run", action="store_true",
                   help="Chỉ load + chunk, không embed/lưu DB")
    p.add_argument("--clear", action="store_true",
                   help="Xoá collection cũ trong PGVector trước khi ingest")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    config = get_config()

    logger.info("Path_Data: %s", config.path_data)
    logger.info("Chunking: size=%d overlap=%d", config.chunking.chunk_size, config.chunking.chunk_overlap)
    logger.info("Embedding: provider=%s model=%s dim=%d batch=%d",
                config.embedding.provider, config.embedding.model,
                config.embedding.dim, config.embedding.batch_size)
    logger.info("Database: collection=%s", config.database.collection_name)


    loader = CleanedDataLoader(config.path_data)
    docs = loader.load_all()
    if not docs:
        logger.error("Không có dữ liệu trong cleaned/. Hãy chạy trước: python -m ingestion.clean_step")
        return
    if args.limit:
        docs = docs[:args.limit]
    logger.info("Đã đọc %d document từ cleaned/", len(docs))


    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.chunking.chunk_size,
        chunk_overlap=config.chunking.chunk_overlap,
        separators=config.chunking.separators,
    )

    lc_docs: list[LCDocument] = []
    for d in docs:
        meta = {
            "doc_id": d.doc_id,
            "kind": d.kind,
            "title": d.title,
            "category": d.category or "",
            "source_id": d.source_id or "",
            "referenced_by": d.referenced_by,
        }
        if d.source_url:
            meta["source"] = d.source_url
        for chunk_text in splitter.split_text(d.content):
            lc_docs.append(LCDocument(page_content=chunk_text, metadata=meta))

    logger.info("Đã tách thành %d chunk", len(lc_docs))
    if not lc_docs:
        logger.warning("Không có chunk nào, dừng.")
        return

    sizes = [len(d.page_content) for d in lc_docs]
    print("\n===== KẾT QUẢ CHUNKING =====")
    print(f"Documents:      {len(docs)}")
    print(f"Chunks:         {len(lc_docs)}")
    print(f"Chunk size:     min={min(sizes)}  max={max(sizes)}  avg={sum(sizes)//len(sizes)}")

    if args.dry_run:
        print("\n[dry-run] Dừng sau chunking, không embed/lưu DB.")
        return


    db = config.database
    emb = config.embedding
    embeddings = VoyageAIEmbeddings(
        model=emb.model,
        batch_size=emb.batch_size,
        voyage_api_key=emb.api_key,
    )

    vectorstore = PGVector(
        embeddings=embeddings,
        collection_name=db.collection_name,
        connection=db.url,
        embedding_length=emb.dim,
        distance_strategy=db.distance_strategy,
        use_jsonb=db.use_jsonb,
        pre_delete_collection=args.clear,
    )

    logger.info("Bắt đầu embed + lưu %d chunk...", len(lc_docs))
    vectorstore.add_documents(lc_docs, batch_size=100)

    print("\n===== KẾT QUẢ EMBED (TẦNG 3) =====")
    print(f"Documents nguồn:   {len(docs)}")
    print(f"Chunks đã lưu:    {len(lc_docs)}")
    print(f"Collection:       {db.collection_name}")


if __name__ == "__main__":
    main()
