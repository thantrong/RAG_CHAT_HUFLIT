"""FastAPI chat app: API hỏi đáp RAG cho sinh viên HUFLIT.

Toàn bộ tham số đọc từ config/app.yaml (port, CORS) và config/database.yaml.

Chạy server:
    .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000

Endpoints:
    GET  /health          -> kiểm tra server + DB
    POST /chat            -> hỏi đáp RAG {"question": "..."}
    GET  /                -> thông tin API
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from pipeline.config import get_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("app")

_config = get_config()


_rag = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _rag
    logger.info("Đang khởi tạo RAG chain...")
    from pipeline.chain import RAGChain
    _rag = RAGChain(_config)
    logger.info("RAG chain sẵn sàng!")
    yield
    logger.info("Shutdown server.")


app = FastAPI(
    title="HUFLIT Student RAG Chat API",
    description="API hỏi đáp cho sinh viên HUFLIT dựa trên dữ liệu portal trường (LangChain + pgvector + Gemini).",
    version="1.0.0",
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=_config.app.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000, description="Câu hỏi của sinh viên")


class SourceItem(BaseModel):
    index: int
    title: str
    category: str
    source_url: str
    doc_id: str
    kind: str
    referenced_by: list[str] = []


class ChatResponse(BaseModel):
    question: str
    answer: str
    sources: list[SourceItem]


@app.get("/")
def root():
    return {
        "name": "HUFLIT Student RAG Chat API",
        "endpoints": {
            "GET /health": "Kiểm tra server",
            "POST /chat": 'Hỏi đáp: {"question": "..."}',
            "GET /docs": "Swagger UI",
        },
    }


@app.get("/health")
def health():
    """Kiểm tra server và kết nối DB."""
    status = {"status": "ok", "rag_ready": _rag is not None}
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(_config.database.url)
        with engine.connect() as conn:
            n = conn.execute(text(
                "SELECT COUNT(*) FROM langchain_pg_embedding"
            )).scalar()
        engine.dispose()
        status["chunks_in_db"] = n
    except Exception as e:
        status["status"] = "degraded"
        status["db_error"] = str(e)
    return status


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    """Hỏi đáp RAG: nhận câu hỏi, trả về câu trả lời + nguồn tham khảo."""
    if _rag is None:
        raise HTTPException(status_code=503, detail="RAG chain chưa sẵn sàng")

    question = req.question.strip()
    logger.info("Câu hỏi: %s", question)

    try:
        result = _rag.ask(question)
    except Exception as e:
        logger.exception("Lỗi khi xử lý câu hỏi")
        raise HTTPException(status_code=500, detail=f"Lỗi xử lý: {e}")

    logger.info("Đã trả lời, %d nguồn", len(result["sources"]))
    return ChatResponse(
        question=question,
        answer=result["answer"],
        sources=[SourceItem(**s) for s in result["sources"]],
    )
