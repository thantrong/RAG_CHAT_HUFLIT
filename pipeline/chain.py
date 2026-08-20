from __future__ import annotations

import logging
from typing import Optional

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from pipeline.config import PipelineConfig, get_config
from pipeline.retriever import HybridRetriever

logger = logging.getLogger(__name__)


_DEFAULT_SYSTEM_PROMPT = (
    "Bạn là trợ lý AI hỗ trợ sinh viên HUFLIT. "
    "Trả lời dựa trên ngữ cảnh bên dưới, bằng tiếng Việt, trích dẫn nguồn [số].\n\n"
    "NGỮ CẢNH:\n{context}"
)

USER_PROMPT = """{question}"""


def format_context(docs) -> str:
    """Ghép các document thành ngữ cảnh có đánh số nguồn."""
    parts = []
    for i, d in enumerate(docs, 1):
        meta = d.metadata or {}
        title = meta.get("title", "")
        category = meta.get("category", "")
        source = meta.get("source", "")
        header = f"[{i}] {title}"
        if category:
            header += f" ({category})"
        if source:
            header += f" - {source}"
        parts.append(f"{header}\n{d.page_content}")
    return "\n\n---\n\n".join(parts)


class RAGChain:
    """Chuỗi RAG hoàn chỉnh: retrieve -> rerank -> generate."""

    def __init__(self, config: Optional[PipelineConfig] = None):
        self.config = config or get_config()
        self.retriever = HybridRetriever(self.config)
        self.llm = self._build_llm()
        self.system_prompt = self.config.llm.system_prompt or _DEFAULT_SYSTEM_PROMPT

    def _build_llm(self) -> ChatOpenAI:
        """Dùng ChatOpenAI trỏ tới endpoint OpenAI-compatible của Google Gemini."""
        lc = self.config.llm
        return ChatOpenAI(
            model=lc.model,
            api_key=lc.api_key or "",
            base_url=lc.endpoint,
            temperature=lc.temperature,
            top_p=lc.top_p,
            max_tokens=lc.max_output_tokens,
            timeout=lc.timeout,
            max_retries=lc.max_retries,
        )


    def ask(self, question: str) -> dict:
        """Hỏi đáp RAG. Trả về {"answer": ..., "sources": [...]}."""
        docs = self.retriever.retrieve(question)
        context = format_context(docs)

        prompt = ChatPromptTemplate.from_messages([
            ("system", self.system_prompt),
            ("human", USER_PROMPT),
        ])
        chain = prompt | self.llm | StrOutputParser()
        answer = chain.invoke({"context": context, "question": question})

        sources = []
        for i, d in enumerate(docs, 1):
            meta = d.metadata or {}
            sources.append({
                "index": i,
                "title": meta.get("title", ""),
                "category": meta.get("category", ""),
                "source_url": meta.get("source", ""),
                "doc_id": meta.get("doc_id", ""),
                "kind": meta.get("kind", ""),
                "referenced_by": meta.get("referenced_by", []),
            })

        return {"answer": answer, "sources": sources}
