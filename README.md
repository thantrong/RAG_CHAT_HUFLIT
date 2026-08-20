# 🎓 RAG_CHAT — Chatbot hỗ trợ sinh viên HUFLIT

Chatbot RAG (Retrieval-Augmented Generation) trả lời câu hỏi của sinh viên
dựa trên dữ liệu thật từ cổng thông tin HUFLIT (thông báo, học bổng, lịch thi,
chương trình đào tạo...). Xây dựng trên **LangChain**.

## 🧱 Tech Stack

| Thành phần | Công nghệ |
|---|---|
| Crawler | requests + BeautifulSoup + pdfplumber |
| Làm sạch NLP | TextCleaner tự viết + thư viện từ rác `junk_phrases.yaml` |
| Embedding | VoyageAI `voyage-4` (1024 chiều) |
| Vector DB | PostgreSQL 16 + pgvector (Docker: `db-postgres-ltw`) |
| Retrieval | Hybrid: PGVector (vector) + BM25 (từ khoá) → fusion → Voyage rerank |
| LLM | Google Gemini `gemini-3.5-flash-lite` (endpoint OpenAI-compatible) |
| API | FastAPI (port 8000) |
| UI | Streamlit (port 8501) |

## 🏗️ Kiến trúc 3 tầng

Mỗi tầng lưu dữ liệu riêng, **kiểm tra được chất lượng trước khi qua tầng sau**:

```
┌─────────────────────────────────────────────────────────────────────┐
│ TẦNG 1 — CRAWL (thu thập dữ liệu thô)                                │
│   cawl/  →  cawl/data/news/{category}/{id}.json                     │
│             cawl/data/attachments/...                                │
│             cawl/data/external_files/  (PDF SharePoint/GDrive)       │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ python -m ingestion.clean_step
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│ TẦNG 2 — CLEAN (làm sạch NLP, DUYỆT ĐƯỢC)                            │
│   ingestion/  →  cawl/data/cleaned/{kind}/{doc_id}.json             │
│                  cawl/data/cleaned/manifest.json                     │
│   >>> Người dùng mở thư mục này duyệt nội dung trước khi embed <<<   │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ python -m ingestion.main --clear
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│ TẦNG 3 — EMBED (vector hoá + lưu trữ)                                │
│   ingestion/main.py  →  PGVector (PostgreSQL) collection student_rag │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ truy vấn lúc runtime
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│ RUNTIME — HỎI ĐÁP                                                    │
│   pipeline/ (retriever + chain)  ←  app/ (FastAPI)  ←  ui/ (Streamlit)│
└─────────────────────────────────────────────────────────────────────┘
```

**doc_id giữ nguyên xuyên suốt 3 tầng** để đối chiếu:
`news-3664` → `cleaned/news/news-3664.json` → chunk metadata `doc_id: news-3664`.

## 📁 Cấu trúc thư mục

```
RAG_CHAT/
├── .env                      # CHỈ SECRET: API keys + DB_PASSWORD (KHÔNG commit)
├── settings.py               # Loader chung: đọc config/*.yaml + secret từ .env
├── requirements.txt
├── README.md
│
├── cawl/                     # TẦNG 1: Crawler
│   ├── main.py               #   CLI chạy crawl
│   ├── config.py             #   Đọc config/crawl.yaml
│   ├── crawler.py            #   Điều phối: frontier → fetch → parse → store
│   ├── frontier.py           #   Queue URL (BFS, dedup qua hash)
│   ├── fetcher.py            #   Tải HTML/file (retry, timeout, politeness)
│   ├── parser.py             #   Tách nội dung HTML (block-aware, sửa lỗi cắt vụn)
│   ├── extractor.py          #   Trích text PDF/DOCX (phát hiện BẢNG, tách cột/dòng)
│   ├── attachment_index.py   #   Dedup attachment theo checksum
│   ├── storage.py            #   Ghi JSON ra cawl/data/
│   └── models.py             #   Dataclass bài viết/attachment
│
├── ingestion/                # TẦNG 2 + 3: Làm sạch + Embed
│   ├── clean_step.py         #   CLI: raw → cleaned/ (bước làm sạch riêng)
│   ├── cleaner.py            #   TextCleaner: NLP cleaning (HTML + text)
│   ├── enricher.py           #   ExternalFileLoader: PDF ngoài → Document (có timeout)
│   ├── loader.py             #   CrawlDataLoader (raw) + CleanedDataLoader (cleaned/)
│   ├── main.py               #   CLI: cleaned/ → chunk → embed → PGVector
│   ├── config.py             #   Đọc config/*.yaml cho ingestion
│   └── models.py             #   Document dataclass
│
├── pipeline/                 # RUNTIME: Retrieval + Generation
│   ├── retriever.py          #   HybridRetriever: vector + BM25 → fusion → rerank
│   ├── chain.py              #   RAGChain: prompt + Gemini (LCEL)
│   ├── config.py             #   Đọc config/*.yaml cho pipeline
│   └── main.py               #   CLI hỏi đáp trực tiếp
│
├── app/                      # API layer
│   └── main.py               #   FastAPI: /health, /chat
│
├── ui/                       # Giao diện
│   └── chat_app.py           #   Streamlit chat
│
├── scripts/
│   └── download_external.py  #   Tải PDF SharePoint (agent-browser) + GDrive (curl)
│
├── config/                   # TOÀN BỘ THAM SỐ CẤU HÌNH (mỗi module 1 file)
│   ├── crawl.yaml            #   cawl: URL, frontier, retry, extraction.timeout, external
│   ├── junk_phrases.yaml     #   ingestion.cleaner: thư viện từ rác
│   ├── chunking.yaml         #   ingestion: chunk size/overlap/separators
│   ├── embedding.yaml        #   ingestion+pipeline: model, dim, batch
│   ├── database.yaml         #   ingestion+pipeline: PG kết nối, collection, distance
│   ├── retrieval.yaml        #   pipeline: vector top-k, BM25, fusion weights
│   ├── reranker.yaml         #   pipeline: Voyage rerank
│   ├── llm.yaml              #   pipeline: Gemini + system_prompt
│   ├── app.yaml              #   app+ui: port, CORS, api_url, timeout, suggestions
│   └── evaluation.yaml       #   (chưa dùng)
│
└── cawl/data/                # DỮ LIỆU (không commit)
    ├── news/{category}/*.json      # Tầng 1: bài viết thô
    ├── attachments/                # Tầng 1: file đính kèm
    ├── external_files/             # Tầng 1: PDF ngoài đã tải
    └── cleaned/{kind}/*.json       # Tầng 2: nội dung đã làm sạch
```

## 🔄 Luồng hoạt động chi tiết (Input → Xử lý → Output)

### TẦNG 1 — Crawl: `python -m cawl.main`

| File | Input | Xử lý | Output |
|---|---|---|---|
| `cawl/config.py` | `config/crawl.yaml` | Parse YAML → `CrawlConfig` | Config singleton |
| `cawl/frontier.py` | URL hạt giống (22 danh mục) | Queue BFS, dedup URL qua hash | URL tiếp theo để tải |
| `cawl/fetcher.py` | URL | GET với retry/timeout/politeness | HTML / file bytes |
| `cawl/parser.py` | HTML bài viết | BeautifulSoup, **block-aware walk** (không cắt vụn text trong `<span>`), tách tiêu đề/nội dung/link ngoài/attachment | Dict bài viết |
| `cawl/extractor.py` | File PDF/DOCX | pdfplumber **phát hiện bảng** → mỗi hàng 1 dòng, cột phân cách ` \| `; text ngoài bảng giữ thứ tự dọc | Text trích xuất |
| `cawl/attachment_index.py` | File attachment | Hash checksum → dedup | `attachments_index.json` (14 file duy nhất) |
| `cawl/storage.py` | Dict bài viết | Ghi JSON | `cawl/data/news/{category}/{source_id}.json` (650 bài) |

**Kết quả tầng 1:** 650 bài viết (22 danh mục) + 14 attachment + 168 file ngoài
(tải bằng `scripts/download_external.py`: 131 SharePoint qua agent-browser + 35 GDrive qua curl).

### TẦNG 2 — Clean: `python -m ingestion.clean_step`

| File | Input | Xử lý | Output |
|---|---|---|---|
| `ingestion/loader.py` (`CrawlDataLoader`) | `cawl/data/news/*.json`, attachments, external_files | Đọc raw, gọi TextCleaner | Danh sách `Document` |
| `ingestion/cleaner.py` (`TextCleaner`) | HTML thô / text thô | 1) NFC normalize 2) xoá ký tự rác (zero-width, nbsp...) 3) xoá cụm rác (`vui lòng xem tại đây`...) 4) hàn token bị tách (`61 /KH` → `61/KH`, chỉ khớp space/tab, **giữ xuống dòng của bảng**) 5) xoá dòng rác, dòng lặp | Text sạch |
| `ingestion/enricher.py` (`ExternalFileLoader`) | `external_files/download_log.json` + file PDF | Trích text (timeout 60s/file, tránh treo) → clean | `Document` kind=external |
| `ingestion/clean_step.py` | Danh sách Document | Ghi mỗi doc ra 1 file JSON + manifest | `cawl/data/cleaned/{kind}/{doc_id}.json` (797 files) |

**Kết quả tầng 2:** 797 documents sạch (650 news + 137 external + 10 attachment),
avg ~8.800 chars/doc. **Người dùng duyệt thư mục `cleaned/` tại đây.**

### TẦNG 3 — Embed: `python -m ingestion.main --clear`

| File | Input | Xử lý | Output |
|---|---|---|---|
| `ingestion/loader.py` (`CleanedDataLoader`) | `cawl/data/cleaned/{kind}/*.json` | Đọc nội dung đã duyệt (KHÔNG đụng raw) | Danh sách `Document` |
| `ingestion/main.py` | Documents | `RecursiveCharacterTextSplitter` (size=1000, overlap=120) → `VoyageAIEmbeddings` (voyage-4, batch 16) → `PGVector.add_documents` | **8588 chunks** trong PostgreSQL |

**Kết quả tầng 3:** collection `student_rag` (bảng `langchain_pg_embedding`), cosine, 1024-dim.

### RUNTIME — Hỏi đáp

```
Người dùng (Streamlit :8501)
    │  POST /chat {"question": "..."}
    ▼
FastAPI app/main.py (:8000)
    │  RAGChain.ask(question)
    ▼
pipeline/retriever.py — HybridRetriever.retrieve()
    ├─ 1. Embed câu hỏi (Voyage voyage-4)                    ~1.4s
    ├─ 2. PGVector similarity search top 25 (≥0.25)          ~0.5s
    ├─ 3. BM25 search top 15 (nạp sẵn trong RAM lúc start)   ~0.2s
    ├─ 4. Fusion: 0.65×vector + 0.35×BM25 (rank-normalized)  → top 10
    └─ 5. Voyage rerank-2.5-lite → top 6                     ~0.6s
    ▼
pipeline/chain.py — RAGChain
    ├─ format_context(): đánh số nguồn [1][2]... kèm title/category/url
    ├─ ChatPromptTemplate (system: trợ lý HUFLIT, trích dẫn [n])
    └─ LCEL: prompt | ChatOpenAI(Gemini flash-lite) | StrOutputParser  ~1.5s
    ▼
{"answer": "...", "sources": [{index, title, category, source_url, doc_id}]}
    ▼
Streamlit hiển thị câu trả lời + expander nguồn
```

**Tổng thời gian trả lời: ~4 giây.**

## 🚀 Cách chạy

```bash
# 0. Môi trường
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# Docker DB: container db-postgres-ltw (postgres/admin, DB student_rag)

# 1. Crawl (chỉ chạy khi cần lấy dữ liệu mới)
python -m cawl.main

# 2. Tải PDF ngoài (SharePoint cần agent-browser: npm i -g agent-browser)
python scripts/download_external.py

# 3. Làm sạch → DUYỆT thư mục cawl/data/cleaned/
python -m ingestion.clean_step

# 4. Embed + lưu PGVector (chỉ chạy khi đã ưng nội dung)
python -m ingestion.main --clear

# 5. Khởi động server
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000   # API
python -m streamlit run ui/chat_app.py --server.port 8501   # UI
```

Mở **http://127.0.0.1:8501** để chat.

## ⚙️ Quy ước cấu hình

**Nguyên tắc: mọi THAM SỐ trong `config/*.yaml`, mọi SECRET trong `.env`.**
Không hardcode tham số trong code Python. `settings.py` là loader chung
(đọc yaml + secret, dựng URL DB).

| File yaml | Module dùng | Tham số chính |
|---|---|---|
| `crawl.yaml` | cawl, ingestion, scripts | base_url, Path_Data, retry, extraction.timeout, external.session |
| `junk_phrases.yaml` | ingestion.cleaner | inline/line patterns, char replacements |
| `chunking.yaml` | ingestion | chunk_size, overlap, separators |
| `embedding.yaml` | ingestion, pipeline | model, dim, batch_size |
| `database.yaml` | ingestion, pipeline, app | host, port, database, username, collection_name, distance |
| `retrieval.yaml` | pipeline | vector.top_k, bm25.top_k, fusion weights, final_top_k |
| `reranker.yaml` | pipeline | model, candidate_count, top_k, enabled |
| `llm.yaml` | pipeline | model, endpoint, temperature, system_prompt |
| `app.yaml` | app, ui | api.port, cors, ui.api_url, timeout, suggestions |

**`.env` (chỉ secret, KHÔNG commit):**
```
DB_PASSWORD=...             # mật khẩu PostgreSQL
VOYAGE_API_KEY=...          # embedding + rerank
GOOGLE_API_KEY=...          # Gemini
HUFLIT_USERNAME=...         # tài khoản trường (SharePoint)
HUFLIT_PASSWORD=...
```

**Muốn đổi tham số** (vd: đổi model, đổi chunk size, đổi port):
sửa file yaml tương ứng rồi restart server — không cần đụng code.

## 📌 Ghi chú vận hành

- **IP bị chặn khi crawl:** portal.huflit.edu.vn có thể chặn IP WiFi nhà;
  dùng hotspot điện thoại nếu gặp lỗi TCP open nhưng HTTP im lặng.
- **PDF phức tạp:** extractor có timeout 60s/file, file treo sẽ bị bỏ qua
  (không chặn pipeline).
- **Bảng trong PDF:** được trích riêng từng hàng/cột (phân cách ` | `),
  số liệu không bị dính.
- **Stopwords:** KHÔNG xoá khỏi nội dung (embedding model cần câu tự nhiên);
  BM25 tự xử lý qua IDF.