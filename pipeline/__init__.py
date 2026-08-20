"""Module pipeline (LangChain): retrieval -> rerank -> LLM trả lời.

    config.py     -> đọc retrieval.yaml, reranker.yaml, llm.yaml
    retriever.py  -> hybrid retrieval (PGVector + BM25 + weighted fusion) + Voyage rerank
    chain.py      -> LangChain chain: prompt + LLM (OpenCode, OpenAI-compatible)
    main.py       -> CLI hỏi đáp thử
"""

from pipeline.chain import RAGChain

__all__ = ["RAGChain"]
