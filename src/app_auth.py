from __future__ import annotations

import base64
import hmac
import mimetypes
import textwrap
from pathlib import Path

import streamlit as st


APP_AUTH_VERSION = "0.4.3"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOGIN_LOGO_PATH = PROJECT_ROOT / "assets" / "greating_logo.png"


def _app_password() -> str:
    try:
        return str(st.secrets.get("APP_PASSWORD", "")).strip()
    except Exception:
        return ""


def _login_logo_html() -> str:
    if not LOGIN_LOGO_PATH.exists():
        return "<div class='gst-logo-fallback'>GREATING</div>"

    mime_type = mimetypes.guess_type(LOGIN_LOGO_PATH.name)[0] or "image/png"
    encoded = base64.b64encode(LOGIN_LOGO_PATH.read_bytes()).decode("ascii")

    return (
        "<div class='gst-logo-wrap'>"
        f"<img src='data:{mime_type};base64,{encoded}' alt='GREATING logo'>"
        "</div>"
    )


# 두벌식 한글 자판을 영문 키 입력으로 환산하기 위한 매핑
_CHOSEONG_KEYS = [
    "r", "R", "s", "e", "E", "f", "a", "q", "Q",
    "t", "T", "d", "w", "W", "c", "z", "x", "v", "g",
]

_JUNGSEONG_KEYS = [
    "k", "o", "i", "O", "j", "p", "u", "P", "h",
    "hk", "ho", "hl", "y", "n", "nj", "np", "nl",
    "b", "m", "ml", "l",
]

_JONGSEONG_KEYS = [
    "",
    "r", "R", "rt", "s", "sw", "sg", "e", "f",
    "fr", "fa", "fq", "ft", "fx", "fv", "fg",
    "a", "q", "qt", "t", "T", "d", "w", "c",
    "z", "x", "v", "g",
]

_COMPAT_JAMO_KEYS = {
    "ㄱ": "r", "ㄲ": "R", "ㄴ": "s", "ㄷ": "e", "ㄸ": "E",
    "ㄹ": "f", "ㅁ": "a", "ㅂ": "q", "ㅃ": "Q", "ㅅ": "t",
    "ㅆ": "T", "ㅇ": "d", "ㅈ": "w", "ㅉ": "W", "ㅊ": "c",
    "ㅋ": "z", "ㅌ": "x", "ㅍ": "v", "ㅎ": "g",
    "ㅏ": "k", "ㅐ": "o", "ㅑ": "i", "ㅒ": "O", "ㅓ": "j",
    "ㅔ": "p", "ㅕ": "u", "ㅖ": "P", "ㅗ": "h", "ㅘ": "hk",
    "ㅙ": "ho", "ㅚ": "hl", "ㅛ": "y", "ㅜ": "n", "ㅝ": "nj",
    "ㅞ": "np", "ㅟ": "nl", "ㅠ": "b", "ㅡ": "m", "ㅢ": "ml",
    "ㅣ": "l",
}


def _normalize_keyboard_password(value: str) -> str:
    """
    비밀번호에 한글이 포함되면 두벌식 영문 키 입력으로 환산한다.

    예:
      그리팅11!!  -> rmflxld11!!
      rmflxld11!! -> rmflxld11!!

    따라서 APP_PASSWORD가 한글/영문 어느 형태로 저장되어 있어도
    두 입력을 동일한 비밀번호로 처리할 수 있다.
    """
    result: list[str] = []

    for char in str(value):
        codepoint = ord(char)

        if 0xAC00 <= codepoint <= 0xD7A3:
            syllable_index = codepoint - 0xAC00

            choseong_index = syllable_index // 588
            jungseong_index = (syllable_index % 588) // 28
            jongseong_index = syllable_index % 28

            result.append(_CHOSEONG_KEYS[choseong_index])
            result.append(_JUNGSEONG_KEYS[jungseong_index])

            if jongseong_index:
                result.append(_JONGSEONG_KEYS[jongseong_index])

            continue

        if char in _COMPAT_JAMO_KEYS:
            result.append(_COMPAT_JAMO_KEYS[char])
            continue

        result.append(char)

    return "".join(result)


def is_authenticated() -> bool:
    return st.session_state.get("authenticated") is True


def render_login() -> bool:
    """
    로그인 완료 시 True.
    미로그인 상태에서는 로그인 화면을 표시하고 False를 반환한다.
    """
    if is_authenticated():
        return True

    css = textwrap.dedent(
        """
        <style>
        :root {
            --gst-olive: #778B49;
            --gst-olive-dark: #667A3C;
            --gst-olive-soft: #EEF2E4;
        }

        /* 로그인 화면 전체 배경 */
        .stApp {
            background:
                radial-gradient(circle at 12% 16%, rgba(119,139,73,.08), transparent 24%),
                radial-gradient(circle at 88% 34%, rgba(119,139,73,.06), transparent 22%),
                linear-gradient(180deg, var(--background-color) 0%, var(--background-color) 100%);
        }

        .gst-shell {
            max-width: 610px;
            margin: 4.5vh auto 0 auto;
        }

        .gst-card {
            background: color-mix(in srgb, var(--secondary-background-color) 92%, transparent);
            border: 1px solid color-mix(in srgb, var(--text-color) 10%, transparent);
            border-radius: 26px;
            padding: 2.0rem 2.5rem 1.8rem 2.5rem;
            box-shadow: 0 20px 55px rgba(26, 34, 18, 0.10);
            backdrop-filter: blur(10px);
        }

        .gst-logo-wrap {
            display: flex;
            justify-content: center;
            align-items: center;
            margin: 0 auto .65rem auto;
            min-height: 42px;
        }

        .gst-logo-wrap img {
            display: block;
            width: auto;
            max-width: 138px;
            max-height: 54px;
            object-fit: contain;
        }

        .gst-logo-fallback {
            text-align: center;
            color: var(--text-color);
            font-size: .78rem;
            font-weight: 800;
            letter-spacing: .18em;
            margin-bottom: .75rem;
        }

        .gst-chart-wrap {
            width: 126px;
            height: 104px;
            margin: .2rem auto .95rem auto;
            position: relative;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        .gst-chart-card {
            position: relative;
            width: 108px;
            height: 78px;
            border-radius: 18px;
            background:
                linear-gradient(145deg,
                    color-mix(in srgb, var(--secondary-background-color) 94%, #fff 6%),
                    color-mix(in srgb, var(--secondary-background-color) 86%, var(--gst-olive-soft) 14%)
                );
            border: 1px solid color-mix(in srgb, var(--text-color) 8%, transparent);
            box-shadow: 0 10px 25px rgba(68, 84, 41, .11);
            display: flex;
            align-items: flex-end;
            justify-content: center;
            gap: 7px;
            padding: 15px 14px 13px 14px;
            box-sizing: border-box;
        }

        .gst-bar {
            width: 12px;
            border-radius: 8px 8px 3px 3px;
            background: color-mix(in srgb, var(--gst-olive) 65%, #d9dfcc 35%);
        }

        .gst-bar.b1 { height: 25px; opacity: .35; }
        .gst-bar.b2 { height: 34px; opacity: .50; }
        .gst-bar.b3 { height: 44px; opacity: .68; }
        .gst-bar.b4 { height: 57px; opacity: 1; }

        .gst-trend-line {
            position: absolute;
            left: 13px;
            top: 19px;
            width: 82px;
            height: 33px;
            overflow: visible;
        }

        .gst-growth-badge {
            position: absolute;
            top: -2px;
            right: -9px;
            padding: 5px 9px;
            border-radius: 10px;
            background: var(--gst-olive);
            color: white;
            font-size: .67rem;
            font-weight: 800;
            box-shadow: 0 5px 12px rgba(80, 99, 48, .20);
        }

        .gst-title {
            text-align: center;
            color: var(--text-color);
            font-size: 2rem;
            line-height: 1.18;
            font-weight: 850;
            letter-spacing: -.035em;
            margin: 0 0 .45rem 0;
        }

        .gst-subtitle {
            text-align: center;
            color: var(--text-color);
            opacity: .62;
            font-size: .95rem;
            margin: 0;
        }

        .gst-divider {
            display: flex;
            align-items: center;
            gap: 0;
            margin: 1.35rem 0 1.3rem 0;
        }

        .gst-divider::before,
        .gst-divider::after {
            content: "";
            height: 1px;
            flex: 1;
            background: color-mix(in srgb, var(--text-color) 10%, transparent);
        }

        .gst-divider span {
            width: 30px;
            height: 3px;
            border-radius: 999px;
            background: var(--gst-olive);
            margin: 0 10px;
        }

        .gst-guide {
            max-width: 520px;
            margin: 1.15rem auto .45rem auto;
            color: var(--text-color);
            font-size: .90rem;
            font-weight: 700;
        }

        .gst-footnote {
            max-width: 520px;
            margin: 1.25rem auto 0 auto;
            padding-top: .9rem;
            border-top: 1px solid color-mix(in srgb, var(--text-color) 9%, transparent);
            text-align: center;
            color: var(--text-color);
            opacity: .42;
            font-size: .70rem;
            letter-spacing: .02em;
        }

        /* Password */
        div[data-testid="stTextInput"] {
            max-width: 520px;
            margin: 0 auto .55rem auto;
        }

        div[data-testid="stTextInput"] input {
            min-height: 48px;
            border-radius: 12px !important;
            color: var(--text-color) !important;
            background: var(--secondary-background-color) !important;
            -webkit-text-fill-color: var(--text-color) !important;
            caret-color: var(--text-color) !important;
        }

        div[data-testid="stTextInput"] input::placeholder {
            color: var(--text-color) !important;
            opacity: .42;
        }

        div[data-testid="stTextInput"] button,
        div[data-testid="stTextInput"] svg {
            color: var(--text-color) !important;
            fill: currentColor !important;
        }

        /* Login button */
        div[data-testid="stButton"] {
            max-width: 520px;
            margin-left: auto;
            margin-right: auto;
        }

        div[data-testid="stButton"] > button[kind="primary"],
        div[data-testid="stButton"] > button {
            min-height: 49px;
            border-radius: 12px;
            border: 1px solid var(--gst-olive-dark) !important;
            background: linear-gradient(135deg, var(--gst-olive), var(--gst-olive-dark)) !important;
            color: #FFFFFF !important;
            font-weight: 800;
            box-shadow: 0 8px 20px rgba(91, 111, 53, .18);
        }

        div[data-testid="stButton"] > button:hover {
            filter: brightness(.97);
            border-color: var(--gst-olive-dark) !important;
            color: #FFFFFF !important;
        }

        /* dark mode 보정 */
        @media (prefers-color-scheme: dark) {
            .gst-title,
            .gst-subtitle,
            .gst-guide,
            .gst-footnote,
            .gst-logo-fallback {
                color: #F5F7F2 !important;
            }

            div[data-testid="stTextInput"] input {
                color: #F5F7F2 !important;
                -webkit-text-fill-color: #F5F7F2 !important;
                caret-color: #F5F7F2 !important;
            }

            div[data-testid="stTextInput"] input::placeholder {
                color: #CBD2C0 !important;
            }

            div[data-testid="stTextInput"] button,
            div[data-testid="stTextInput"] svg {
                color: #F5F7F2 !important;
            }
        }
        </style>
        """
    ).strip()

    st.markdown(css, unsafe_allow_html=True)

    logo_html = _login_logo_html()

    # HTML을 줄바꿈/들여쓰기 없는 문자열로 구성한다.
    # Streamlit Markdown이 4칸 이상 들여쓴 HTML을 code block으로
    # 오인하는 문제를 원천적으로 막는다.
    hero_html = (
        '<div class="gst-shell">'
        '<div class="gst-card">'
        f'{logo_html}'
        '<div class="gst-chart-wrap">'
        '<div class="gst-chart-card">'
        '<div class="gst-bar b1"></div>'
        '<div class="gst-bar b2"></div>'
        '<div class="gst-bar b3"></div>'
        '<div class="gst-bar b4"></div>'
        '<svg class="gst-trend-line" viewBox="0 0 82 33" fill="none" '
        'xmlns="http://www.w3.org/2000/svg">'
        '<path d="M2 29 C14 19, 22 23, 31 16 C42 7, 50 14, 61 7 C68 3, 75 5, 80 2" '
        'stroke="#778B49" stroke-width="2.6" stroke-linecap="round"></path>'
        '<circle cx="2" cy="29" r="2.8" fill="#9BAC78"></circle>'
        '<circle cx="31" cy="16" r="2.8" fill="#9BAC78"></circle>'
        '<circle cx="61" cy="7" r="2.8" fill="#9BAC78"></circle>'
        '<circle cx="80" cy="2" r="2.8" fill="#778B49"></circle>'
        '</svg>'
        '<div class="gst-growth-badge">↑ +24%</div>'
        '</div>'
        '</div>'
        '<div class="gst-title">Greating Search Trend</div>'
        '<div class="gst-subtitle">그리팅 검색어 트렌드를 알아보세요</div>'
        '<div class="gst-divider"><span></span></div>'
        '</div>'
        '</div>'
    )

    st.markdown(hero_html, unsafe_allow_html=True)

    st.markdown(
        '<div class="gst-guide">접근 비밀번호를 입력해주세요</div>',
        unsafe_allow_html=True,
    )

    password = st.text_input(
        "비밀번호",
        type="password",
        label_visibility="collapsed",
        placeholder="비밀번호",
        key="greating_search_login_password",
    )

    if st.button(
        "로그인",
        type="primary",
        use_container_width=True,
        key="greating_search_login_button",
    ):
        expected = _app_password()

        if not expected:
            st.error("APP_PASSWORD가 설정되지 않았습니다.")
            return False

        # 한/영 전환 상태가 달라도 같은 키 입력을 같은 비밀번호로 처리한다.
        # 예: "그리팅11!!" == "rmflxld11!!"
        normalized_password = _normalize_keyboard_password(password)
        normalized_expected = _normalize_keyboard_password(expected)

        password_bytes = normalized_password.encode("utf-8")
        expected_bytes = normalized_expected.encode("utf-8")

        if hmac.compare_digest(password_bytes, expected_bytes):
            st.session_state["authenticated"] = True
            st.rerun()

        st.error("비밀번호가 올바르지 않습니다.")

    st.markdown(
        '<div class="gst-footnote">'
        'Greating Marketing Team · Search Insight Dashboard'
        '</div>',
        unsafe_allow_html=True,
    )

    return False


def require_authenticated() -> None:
    if is_authenticated():
        return

    try:
        st.switch_page("app.py")
    except Exception:
        st.warning("먼저 로그인해주세요.")
        st.page_link(
            "app.py",
            label="로그인으로 이동",
            icon="🔐",
        )
        st.stop()


def logout() -> None:
    st.session_state.pop("authenticated", None)
    st.session_state.pop("greating_search_login_password", None)
    st.rerun()


def render_footer(version_text: str) -> None:
    """
    Home / Greating Search / NAVER Food Trend 공통 footer.
    """
    footer_css = textwrap.dedent(
        """
        <style>
        .greating-footer {
            border-top: 1px solid color-mix(in srgb, var(--text-color) 10%, transparent);
            margin-top: 2.2rem;
            padding-top: .8rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 1rem;
            color: var(--text-color);
            opacity: .46;
            font-size: .73rem;
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
        """
    ).strip()

    footer_html = (
        '<div class="greating-footer">'
        '<div class="greating-footer-left">'
        '© 2026 Greating Marketing Team. All rights reserved. '
        '| Designed &amp; Developed by 이선영 책임'
        '</div>'
        f'<div class="greating-footer-right">{version_text}</div>'
        '</div>'
    )

    st.markdown(footer_css, unsafe_allow_html=True)
    st.markdown(footer_html, unsafe_allow_html=True)
