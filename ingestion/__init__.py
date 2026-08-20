"""Module ingestion (LangChain): đọc dữ liệu crawl -> tách chunk -> embed -> PGVector.

Pipeline:
    loader.py   -> đọc news JSON + PDF attachments -> Document
    main.py     -> CLI: RecursiveCharacterTextSplitter + VoyageAIEmbeddings + PGVector
"""

from ingestion.models import Document

__all__ = ["Document"]
