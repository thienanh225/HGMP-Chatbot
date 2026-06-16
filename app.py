"""
HealthGMP — Vietnamese chatbot (Streamlit UI + model-comparison rig).

Thin UI over the orchestrator. The UI builds a ChatRequest, picks the model at
runtime (provider + model + key), and renders the ChatResponse. All real logic
(contract, guardrail, retrieval, routing) lives in the orchestrator — the same
code a production FastAPI back end would call.

Run:  cd chatbot && streamlit run app.py
Keys: paste in the sidebar (session-only) or prefill via .streamlit/secrets.toml.
No key? Pick "Offline (demo)" to click through the full flow with canned replies.
"""

from __future__ import annotations

import uuid

import streamlit as st

import orchestrator
from contract import ChatRequest
from escalation import log_conversation, log_escalation, log_feedback
from gateway import PROVIDERS, GatewaySettings

st.set_page_config(page_title="Trợ lý sức khỏe HealthGMP", page_icon="💬")


def _secret(key: str, default: str = "") -> str:
    """Read a Streamlit secret safely (returns default if no secrets.toml)."""
    try:
        return str(st.secrets.get(key, default))
    except Exception:
        return default


def _all_secrets() -> dict | None:
    """All secrets as a dict, or None if no secrets.toml is present."""
    try:
        return dict(st.secrets)
    except Exception:
        return None


def _check_password() -> bool:
    """Shared-password gate for the public link. No gate if APP_PASSWORD is unset."""
    required = _secret("APP_PASSWORD")
    if not required or st.session_state.get("authed"):
        return True
    st.title("Trợ lý sức khỏe HealthGMP")
    st.caption("Khu vực thử nghiệm nội bộ — vui lòng nhập mật khẩu để tiếp tục.")
    with st.form("login"):
        pw = st.text_input("Mật khẩu", type="password")
        if st.form_submit_button("Vào") and pw:
            import hmac
            if hmac.compare_digest(pw, required):
                st.session_state.authed = True
                st.rerun()
            else:
                st.error("Sai mật khẩu, vui lòng thử lại.")
    return False


OFFLINE = "Offline (demo — không cần key)"

ROUTE_LABELS = {
    "qualified-person": "🩺 Chuyển chuyên gia y tế",
    "customer-service": "📞 Chuyển CSKH",
    "account-management": "📑 Chuyển quản lý công nợ (B2B)",
    "sales": "🤝 Chuyển bộ phận kinh doanh (B2B)",
}

# ---------------------------------------------------------------------------
# Session bootstrap
# ---------------------------------------------------------------------------
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
if "messages" not in st.session_state:
    st.session_state.messages = []
if "model_locked" not in st.session_state:
    st.session_state.model_locked = False
if "locked_settings" not in st.session_state:
    st.session_state.locked_settings = {}
if "feedback_given" not in st.session_state:
    st.session_state.feedback_given = {}  # turn_id → "like" | "dislike"


def _reset_chat() -> None:
    orchestrator.reset_session(st.session_state.session_id)
    st.session_state.session_id = str(uuid.uuid4())
    st.session_state.messages = []
    st.session_state.model_locked = False
    st.session_state.locked_settings = {}
    # ponytail: keep feedback_given — no reason to wipe history across chats


if not _check_password():
    st.stop()


# ---------------------------------------------------------------------------
# Sidebar — model switcher, audience, config
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Mô hình")
    st.caption("🔑 Khóa API được đọc từ secrets.toml phía máy chủ — giao diện không hiển thị và không lưu khóa.")

    configured = {n: m for n, m in PROVIDERS.items() if _secret(m["key_env"]).strip()}
    model_opts = [(f"{n} — {mdl}", n, mdl) for n, m in configured.items() for mdl in m["models"]]
    model_opts.append((OFFLINE, OFFLINE, "stub/demo"))
    labels = [o[0] for o in model_opts]

    if not configured:
        st.warning("Chưa có khóa API nào trong secrets.toml. Hãy điền khóa, hoặc dùng Offline (demo).")

    locked = st.session_state.model_locked
    ls = st.session_state.locked_settings

    if locked:
        # ponytail: show locked state; no widget needed
        st.info(f"🔒 **{ls.get('provider')} — {ls.get('model_id')}**  \nĐổi mô hình → bắt đầu cuộc trò chuyện mới.")
        provider  = ls["provider"]
        model_id  = ls["model_id"]
        config    = ls["config"]
    else:
        sel = st.selectbox("Chọn mô hình để trò chuyện", labels)
        _, provider, model_id = model_opts[labels.index(sel)]

        with st.expander("Nâng cao — tự nhập model"):
            if configured:
                adv_p = st.selectbox("Provider", list(configured))
                adv_m = st.text_input("Model id", placeholder=configured[adv_p]["models"][0])
                if adv_m.strip():
                    provider, model_id = adv_p, adv_m.strip()
            else:
                st.caption("Cần ít nhất một khóa API trong secrets.toml.")

        st.caption(f"Đang dùng: **{provider} — {model_id}**")

    # Key resolved server-side from secrets; never shown in the UI.
    api_key = "" if provider == OFFLINE else _secret(PROVIDERS.get(provider, {}).get("key_env", ""))

    st.divider()
    st.header("🎯 Ngữ cảnh")
    audience_label = st.radio("Đối tượng", ["Khách hàng (B2C)", "Nhân viên phân phối (B2B)"])
    audience = "b2b" if audience_label.startswith("Nhân viên") else "b2c"

    if not locked:
        config = st.radio(
            "Chế độ (rig)", ["full", "harness", "raw"],
            captions=["Prompt + guardrail + kho tri thức (sản xuất)",
                      "Prompt + guardrail (không kho tri thức)",
                      "Mô hình trần (so sánh đối chứng)"],
        )

    st.button("🧹 Cuộc trò chuyện mới", on_click=_reset_chat, use_container_width=True)

    st.divider()
    st.header("💬 Góp ý chung")
    feedback = st.text_area("Nhận xét về chatbot:", key="feedback_box")
    if st.button("Gửi góp ý", use_container_width=True):
        if feedback.strip():
            dest = log_feedback(feedback.strip(), st.session_state.session_id,
                                secrets=_all_secrets())
            st.success("Đã ghi nhận góp ý. Cảm ơn anh/chị!" + (" (Sheet)" if dest == "webhook" else " (CSV)"))
        else:
            st.warning("Vui lòng nhập nội dung trước khi gửi.")


settings = GatewaySettings(
    provider=provider, model=model_id, api_key=api_key,
    max_tokens=1000, run_guardrail=(config != "raw"), retrieval_k=4,
)

# ---------------------------------------------------------------------------
# Main chat
# ---------------------------------------------------------------------------
st.title("Trợ lý sức khỏe HealthGMP")
st.caption(
    "Prototype nội bộ — thông tin chỉ mang tính tham khảo. Thực phẩm bảo vệ sức khỏe "
    "không phải là thuốc và không có tác dụng thay thế thuốc chữa bệnh."
)

# Render message history with per-turn feedback buttons on assistant messages
for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.write(m["content"])
        if m.get("meta"):
            st.caption(m["meta"])

        if m["role"] == "assistant":
            turn_id = m.get("turn_id", "")
            given = st.session_state.feedback_given.get(turn_id)

            if turn_id and given is None:
                col1, col2, _ = st.columns([1, 1, 10])
                with col1:
                    if st.button("👍", key=f"like_{turn_id}", help="Câu trả lời tốt"):
                        st.session_state.feedback_given[turn_id] = "like"
                        log_feedback("", st.session_state.session_id,
                                     turn_id=turn_id, rating="like",
                                     secrets=_all_secrets())
                        st.rerun()
                with col2:
                    if st.button("👎", key=f"dislike_{turn_id}", help="Câu trả lời chưa tốt"):
                        st.session_state.feedback_given[turn_id] = "dislike"
                        log_feedback("", st.session_state.session_id,
                                     turn_id=turn_id, rating="dislike",
                                     secrets=_all_secrets())
                        st.rerun()
            elif turn_id and given:
                icon = "👍" if given == "like" else "👎"
                st.caption(f"{icon} Cảm ơn góp ý của anh/chị!")


if question := st.chat_input("Nhập câu hỏi…"):
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.write(question)

    needs_key = provider != OFFLINE and not api_key.strip()

    with st.chat_message("assistant"):
        if needs_key:
            warn = f"Provider {provider} chưa có khóa API trong secrets.toml"
            st.warning(f"{warn}. Hãy thêm khóa, hoặc chọn 'Offline (demo)'.")
            st.session_state.messages.append({"role": "assistant", "content": f"⚠️ {warn}."})
        else:
            turn_id = str(uuid.uuid4())  # stamped on this turn's log row AND its 👍/👎 feedback
            with st.spinner("Đang xử lý…"):
                req = ChatRequest(message=question, session_id=st.session_state.session_id,
                                  audience=audience, config=config)
                try:
                    resp = orchestrator.handle_chat(req, settings)
                    answer, route = resp.answer, resp.route
                    bits = [f"model: {resp.model_used}", f"chế độ: {resp.config}"]
                    if resp.sources:
                        bits.append("nguồn: " + ", ".join(resp.sources))
                    if route:
                        bits.append(ROUTE_LABELS.get(route, route))
                    meta = " · ".join(bits)
                    secrets = _all_secrets()
                    if route:
                        log_escalation(question, st.session_state.session_id, route, secrets=secrets)
                    log_conversation(st.session_state.session_id, audience, resp.model_used,
                                     route, resp.sources, question, answer,
                                     turn_id=turn_id, secrets=secrets)
                except Exception as e:
                    answer = ("Xin lỗi anh/chị, hệ thống gặp sự cố khi gọi mô hình. "
                              "Vui lòng kiểm tra API key/model hoặc thử lại sau ít phút.")
                    meta = f"lỗi: {type(e).__name__}"

            st.write(answer)
            st.caption(meta)
            st.session_state.messages.append({
                "role": "assistant", "content": answer, "meta": meta, "turn_id": turn_id,
            })

            # Lock the model after the first successful turn
            if not st.session_state.model_locked:
                st.session_state.model_locked = True
                st.session_state.locked_settings = {
                    "provider": provider, "model_id": model_id, "config": config,
                }
