from __future__ import annotations

import streamlit as st

from src.app_auth import logout, render_footer, render_login

APP_VERSION = "0.3.1"

st.set_page_config(
    page_title="Greating Search Dashboard",
    page_icon="🔎",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .block-container {
        max-width: 1180px;
        padding-top: 3.2rem;
        padding-bottom: 3rem;
    }
    .login-wrap {
        max-width: 520px;
        margin: 8vh auto 1.1rem auto;
        text-align: center;
    }
    .login-kicker {
        color: #107C41;
        font-weight: 850;
        font-size: 0.78rem;
        letter-spacing: 0.12em;
        margin-bottom: 0.4rem;
    }
    .login-title {
        font-size: 2rem;
        font-weight: 850;
        color: #151b26;
        margin-bottom: 0.35rem;
    }
    .login-caption {
        color: #7b8493;
        font-size: 0.9rem;
    }
    div[data-testid="stTextInput"], div[data-testid="stButton"] {
        max-width: 520px;
        margin-left: auto;
        margin-right: auto;
    }
    .home-kicker {
        color: #107C41;
        font-weight: 850;
        font-size: 0.8rem;
        line-height: 1.55;
        letter-spacing: 0.10em;
        margin-top: 0.25rem;
        margin-bottom: 0.25rem;
    }
    .home-title {
        font-size: 2rem;
        font-weight: 850;
        letter-spacing: -0.035em;
        color: #151b26;
        margin-bottom: 0.35rem;
    }
    .home-caption {
        color: #7b8493;
        font-size: 0.92rem;
        margin-bottom: 1.35rem;
    }
    .nav-card {
        border: 1px solid #e3e7ec;
        border-radius: 14px;
        padding: 1.15rem 1.2rem 0.9rem 1.2rem;
        min-height: 132px;
        background: #fff;
    }
    .nav-card-title {
        font-size: 1.08rem;
        font-weight: 800;
        color: #1d2939;
        margin-bottom: 0.35rem;
    }
    .nav-card-desc {
        color: #667085;
        font-size: 0.85rem;
        line-height: 1.55;
    }
    .nav-button-spacer {
        height: 0.65rem;
    }
    div[data-testid="stButton"] > button {
        border-radius: 9px;
        min-height: 2.75rem;
        font-weight: 750;
    }
    #MainMenu, footer { visibility: hidden; }
    </style>
    """,
    unsafe_allow_html=True,
)

if not render_login():
    # 로그인 전에는 multipage sidebar를 숨긴다.
    st.markdown(
        "<style>[data-testid='stSidebar']{display:none;}</style>",
        unsafe_allow_html=True,
    )
    st.stop()

header, action = st.columns([5, 1])
with header:
    st.markdown('<div class="home-kicker">GREATING SEARCH</div>', unsafe_allow_html=True)
    st.markdown('<div class="home-title">Search Insight Dashboard 🔎</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="home-caption">그리팅몰 내부 검색과 외부 식품 검색 트렌드를 한 곳에서 확인합니다.</div>',
        unsafe_allow_html=True,
    )
with action:
    if st.button("로그아웃", use_container_width=True):
        logout()

st.markdown("### 대시보드 선택")

c1, c2 = st.columns(2, gap="large")

with c1:
    st.markdown(
        """
        <div class="nav-card">
          <div class="nav-card-title">🔎 GREATING SEARCH</div>
          <div class="nav-card-desc">GA4 기반 그리팅몰 내부 검색어. 분석기간, 전일·전주·4주평균·Custom 비교와 검색어 Top 50을 확인합니다.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown('<div class="nav-button-spacer"></div>', unsafe_allow_html=True)
    if st.button(
        "🔎 그리팅몰 검색어 보기",
        use_container_width=True,
        key="home_greating_search",
    ):
        st.switch_page("pages/01_Greating_Search.py")

with c2:
    st.markdown(
        """
        <div class="nav-card">
          <div class="nav-card-title">🔥 NAVER FOOD TREND</div>
          <div class="nav-card-desc">NAVER 데이터랩 식품 인기검색어 TOP 500 누적 데이터. 분석일별 순위, 신규 진입, 급상승·급락, 30일 추이를 확인합니다.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown('<div class="nav-button-spacer"></div>', unsafe_allow_html=True)
    if st.button(
        "🔥 네이버 식품 트렌드 보기",
        use_container_width=True,
        key="home_naver_food_trend",
    ):
        st.switch_page("pages/02_NAVER_Food_Trend.py")

render_footer(f"Greating Search Dashboard v{APP_VERSION}")
