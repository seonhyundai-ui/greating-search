from __future__ import annotations

import hmac
import streamlit as st


def _app_password() -> str:
    try:
        return str(st.secrets.get("APP_PASSWORD", "")).strip()
    except Exception:
        return ""


def is_authenticated() -> bool:
    return st.session_state.get("authenticated") is True


def render_login() -> bool:
    if is_authenticated():
        return True

    st.markdown(
        "<div class='login-wrap'>"
        "<div class='login-kicker'>GREATING SEARCH</div>"
        "<div class='login-title'>Search Insight 🔐</div>"
        "<div class='login-caption'>접근 비밀번호를 입력해주세요.</div>"
        "</div>",
        unsafe_allow_html=True,
    )

    password = st.text_input(
        "비밀번호",
        type="password",
        label_visibility="collapsed",
        placeholder="비밀번호",
    )

    if st.button("로그인", type="primary", use_container_width=True):
        expected = _app_password()
        if not expected:
            st.error("APP_PASSWORD가 설정되지 않았습니다.")
            return False

        if hmac.compare_digest(str(password), str(expected)):
            st.session_state["authenticated"] = True
            st.rerun()

        st.error("비밀번호가 올바르지 않습니다.")

    return False


def require_authenticated() -> None:
    if is_authenticated():
        return

    # 직접 페이지 URL로 진입해도 데이터는 보여주지 않는다.
    try:
        st.switch_page("app.py")
    except Exception:
        st.warning("먼저 로그인해주세요.")
        st.page_link("app.py", label="로그인으로 이동", icon="🔐")
        st.stop()


def logout() -> None:
    st.session_state.pop("authenticated", None)
    st.rerun()

def render_footer(version_text: str) -> None:
    st.markdown(
        """
        <style>
        .greating-footer {
            border-top: 1px solid #EAECF0;
            margin-top: 2.2rem;
            padding-top: 0.8rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 1rem;
            color: #98A2B3;
            font-size: 0.76rem;
            line-height: 1.4;
        }
        .greating-footer-left {
            text-align: left;
            flex: 1 1 auto;
        }
        .greating-footer-right {
            text-align: right;
            flex: 0 0 auto;
            white-space: nowrap;
        }
        @media (max-width: 760px) {
            .greating-footer {
                flex-direction: column;
                align-items: flex-start;
            }
            .greating-footer-right {
                text-align: left;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""
        <div class="greating-footer">
            <div class="greating-footer-left">
                © 2026 Greating Marketing Team. All rights reserved. | Designed &amp; Developed by 이선영 책임
            </div>
            <div class="greating-footer-right">{version_text}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

