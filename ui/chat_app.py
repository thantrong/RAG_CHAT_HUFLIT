from __future__ import annotations

import os

import requests
import streamlit as st

from pipeline.config import get_config

_cfg = get_config().app
API_URL = _cfg.ui_api_url
REQUEST_TIMEOUT = _cfg.ui_request_timeout
HEALTH_TIMEOUT = _cfg.ui_health_check_timeout
SUGGESTIONS = _cfg.ui_suggestions


st.set_page_config(
    page_title="Trợ lý sinh viên HUFLIT",
    page_icon="🎓",
    layout="centered",
)


def check_health() -> dict | None:
    """Kiểm tra backend FastAPI có đang chạy không."""
    try:
        r = requests.get(f"{API_URL}/health", timeout=HEALTH_TIMEOUT)
        return r.json()
    except Exception:
        return None


def ask_api(question: str) -> dict:
    """Gửi câu hỏi tới backend RAG."""
    r = requests.post(
        f"{API_URL}/chat",
        json={"question": question},
        timeout=REQUEST_TIMEOUT,
    )
    r.raise_for_status()
    return r.json()


def render_sources(sources: list[dict]) -> None:
    """Hiển thị nguồn tham khảo trong expander."""
    with st.expander(f"📚 Nguồn tham khảo ({len(sources)})", expanded=False):
        for s in sources:
            line = f"**[{s['index']}] {s['title']}**"
            if s.get("category"):
                line += f"  \n*{s['category']}*"
            st.markdown(line)
            if s.get("source_url"):
                st.markdown(f"🔗 [{s['source_url'][:70]}...]({s['source_url']})")
            if s.get("referenced_by"):
                st.caption(f"Được tham chiếu bởi thông báo: {', '.join(s['referenced_by'])}")
            st.divider()


with st.sidebar:
    st.title("🎓 HUFLIT Assistant")
    st.caption("Trợ lý hỏi đáp cho sinh viên HUFLIT")
    st.divider()

    health = check_health()
    if health and health.get("rag_ready"):
        st.success("🟢 Backend hoạt động")
        st.metric("Chunks trong DB", health.get("chunks_in_db", "?"))
    else:
        st.error("🔴 Backend chưa chạy")
        st.code(".venv/bin/uvicorn app.main:app --port 8000", language="bash")

    st.divider()
    if st.button("🗑️ Xoá lịch sử chat", use_container_width=True):
        st.session_state.messages = []
        st.rerun()

    st.divider()
    st.markdown("**💡 Câu hỏi gợi ý:**")
    for s in SUGGESTIONS:
        if st.button(s, use_container_width=True, key=f"sug_{s}"):
            st.session_state.pending_question = s
            st.rerun()


st.title("💬 Trợ lý sinh viên HUFLIT")
st.caption("Hỏi đáp về thông báo, quy định, học phí, học bổng, lịch thi... của trường HUFLIT")


if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("sources"):
            render_sources(msg["sources"])


user_input = st.chat_input("Nhập câu hỏi của bạn...")


pending = st.session_state.pop("pending_question", None)
question = user_input or pending

if question:
    if not health or not health.get("rag_ready"):
        st.error("⚠️ Backend chưa chạy. Hãy khởi động: .venv/bin/uvicorn app.main:app --port 8000")
    else:

        st.session_state.messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)


        with st.chat_message("assistant"):
            with st.spinner("Đang tìm kiếm thông tin..."):
                try:
                    result = ask_api(question)
                    answer = result["answer"]
                    sources = result.get("sources", [])
                    st.markdown(answer)
                    if sources:
                        render_sources(sources)
                    st.session_state.messages.append(
                        {"role": "assistant", "content": answer, "sources": sources}
                    )
                except requests.exceptions.ConnectionError:
                    st.error("❌ Không kết nối được backend. Kiểm tra server FastAPI.")
                except Exception as e:
                    st.error(f"❌ Lỗi: {e}")
