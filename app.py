from __future__ import annotations

import streamlit as st

from src.app_auth import render_login

APP_VERSION = "0.4.2"

st.set_page_config(
    page_title="Greating Search Trend",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Streamlit 기본 UI 최소화
st.markdown(
    """
    <style>
    #MainMenu,
    footer {
        visibility: hidden;
    }

    header[data-testid="stHeader"] {
        background: transparent;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------
# LOGIN
# ---------------------------------------------------------------------
# app_auth.py가 로그인 화면의 전체 디자인을 담당한다.
# 로그인 전에는 사이드바/접기 버튼을 완전히 숨기고 로그인 화면만 표시한다.
if not render_login():
    st.markdown(
        """
        <style>
        [data-testid="stSidebar"] {
            display: none !important;
        }

        [data-testid="collapsedControl"] {
            display: none !important;
        }

        /* 로그인 화면에서는 app 본문 폭 제한을 두지 않는다. */
        .block-container {
            max-width: 1440px !important;
            padding-top: 1.5rem !important;
            padding-bottom: 2.5rem !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.stop()

# ---------------------------------------------------------------------
# AUTHENTICATED APP
# ---------------------------------------------------------------------
# 로그인 완료 후에만 실제 대시보드용 레이아웃을 적용한다.
st.markdown(
    """
    <style>
    .block-container {
        max-width: 1180px;
        padding-top: 2.4rem;
        padding-bottom: 3rem;
    }

    [data-testid="stSidebar"] {
        display: block !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# 한글 페이지명으로 네비게이션 표시
pages = [
    st.Page(
        "pages/00_Home.py",
        title="홈",
        icon="🏠",
        default=True,
    ),
    st.Page(
        "pages/01_Greating_Search.py",
        title="그리팅몰 검색어",
        icon="🔎",
    ),
    st.Page(
        "pages/02_NAVER_Food_Trend.py",
        title="네이버 검색 트렌드",
        icon="🔥",
    ),
]

navigation = st.navigation(
    pages,
    position="sidebar",
)

navigation.run()
