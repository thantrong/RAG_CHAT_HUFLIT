"""Hybrid Retriever (LangChain): PGVector + BM25 + weighted fusion + Voyage rerank.

Toàn bộ tham số đọc từ config/ (retrieval.yaml, reranker.yaml,
database.yaml, embedding.yaml). Secret đọc từ .env qua settings.py.

Quy trình:
1. Vector search (PGVector cosine) -> vector.top_k
2. BM25 keyword search (toàn bộ corpus trong DB) -> bm25.top_k
3. Weighted fusion: vector_weight*vector + bm25_weight*bm25 -> final_top_k
4. Rerank bằng Voyage rerank API -> reranker.top_k kết quả cuối
"""

from __future__ import annotations

import logging
from typing import Optional

from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document as LCDocument
from langchain_postgres import PGVector
from langchain_voyageai import VoyageAIEmbeddings, VoyageAIRerank

from pipeline.config import PipelineConfig, get_config

logger = logging.getLogger(__name__)


class HybridRetriever:
    """Retriever kết hợp vector + BM25 + rerank."""

    def __init__(self, config: Optional[PipelineConfig] = None):
        self.config = config or get_config()
        self._vectorstore: Optional[PGVector] = None
        self._bm25: Optional[BM25Retriever] = None
        self._reranker: Optional[VoyageAIRerank] = None


    @property
    def vectorstore(self) -> PGVector:
        if self._vectorstore is None:
            db = self.config.database
            emb = self.config.embedding
            embeddings = VoyageAIEmbeddings(
                model=emb.model,
                voyage_api_key=emb.api_key,
            )
            self._vectorstore = PGVector(
                embeddings=embeddings,
                collection_name=db.collection_name,
                connection=db.url,
                embedding_length=emb.dim,
                distance_strategy=db.distance_strategy,
                use_jsonb=db.use_jsonb,
            )
        return self._vectorstore

    @property
    def bm25(self) -> BM25Retriever:
        """BM25 trên toàn bộ corpus (nạp từ DB một lần)."""
        if self._bm25 is None:
            docs = self._load_all_docs()
            logger.info("Nạp %d chunk vào BM25", len(docs))
            self._bm25 = BM25Retriever.from_documents(
                docs, k=self.config.retrieval.bm25_top_k
            )
        return self._bm25

    @property
    def reranker(self) -> VoyageAIRerank:
        if self._reranker is None:
            rc = self.config.reranker
            self._reranker = VoyageAIRerank(
                model=rc.model,
                top_k=rc.top_k,
                voyage_api_key=rc.api_key,
            )
        return self._reranker

    def _load_all_docs(self) -> list[LCDocument]:
        """Đọc toàn bộ chunks từ PGVector (không cần embedding)."""
        from sqlalchemy import create_engine, text

        db = self.config.database
        engine = create_engine(db.url)
        docs: list[LCDocument] = []
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT document, cmetadata FROM langchain_pg_embedding "
                    "WHERE collection_id = (SELECT uuid FROM langchain_pg_collection WHERE name = :name)"
                ),
                {"name": db.collection_name},
            ).fetchall()
        engine.dispose()
        for document, meta in rows:
            docs.append(LCDocument(page_content=document, metadata=meta or {}))
        return docs


    def retrieve(self, query: str) -> list[LCDocument]:
        """Truy xuất hybrid + rerank. Trả về top_k documents cuối cùng."""
        rc = self.config.retrieval


        vector_docs = self.vectorstore.similarity_search_with_relevance_scores(
            query, k=rc.vector_top_k
        )

        vector_docs = [(d, s) for d, s in vector_docs if s >= rc.vector_score_threshold]


        bm25_docs = self.bm25.invoke(query)


        fused = self._fuse(vector_docs, bm25_docs)


        if self.config.reranker.enabled and fused:
            candidates = fused[: self.config.reranker.candidate_count]
            reranked = self.reranker.compress_documents(documents=candidates, query=query)
            logger.info("Rerank %d -> %d", len(candidates), len(reranked))
            return list(reranked)

        return fused[: rc.final_top_k]


    def _fuse(
        self,
        vector_docs: list[tuple[LCDocument, float]],
        bm25_docs: list[LCDocument],
    ) -> list[LCDocument]:
        """Weighted fusion theo điểm chuẩn hoá."""
        rc = self.config.retrieval
        scores: dict[str, float] = {}
        doc_map: dict[str, LCDocument] = {}


        for d, s in vector_docs:
            key = self._doc_key(d)
            scores[key] = scores.get(key, 0.0) + rc.vector_weight * s
            doc_map[key] = d


        n = len(bm25_docs) or 1
        for rank, d in enumerate(bm25_docs):
            key = self._doc_key(d)
            rank_score = 1.0 - rank / n
            scores[key] = scores.get(key, 0.0) + rc.bm25_weight * rank_score
            doc_map.setdefault(key, d)

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [doc_map[k] for k, _ in ranked[: rc.final_top_k]]

    @staticmethod
    def _doc_key(d: LCDocument) -> str:
        """Định danh chunk để fusion (dùng id trong metadata hoặc hash text)."""
        meta = d.metadata or {}
        if "id" in meta:
            return str(meta["id"])
        return str(hash(d.page_content))
