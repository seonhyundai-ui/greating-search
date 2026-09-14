from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import streamlit as st

from src.app_auth import (
    logout,
    render_footer,
    require_authenticated,
)
from src.naver_food_dashboard import load_naver_food_meta
from src.naver_food_to_sheets import run_manual

APP_VERSION = "0.5.0"

require_authenticated()

st.markdown(
    """
    <style>
    .block-container {
        max-width: 1180px;
        padding-top: 3.2rem;
        padding-bottom: 3rem;
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
    .data-admin-card {
        border: 1px solid color-mix(in srgb, var(--text-color) 10%, transparent);
        border-radius: 14px;
        padding: 1rem 1.1rem 0.85rem 1.1rem;
        background: var(--secondary-background-color);
        margin-top: 0.25rem;
    }
    .data-admin-title {
        color: var(--text-color);
        font-size: 1rem;
        font-weight: 800;
        margin-bottom: 0.25rem;
    }
    .data-admin-desc {
        color: var(--text-color);
        opacity: 0.62;
        font-size: 0.82rem;
        line-height: 1.5;
    }
    #MainMenu, footer {
        visibility: hidden;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

header, action = st.columns([5, 1])

with header:
    st.markdown(
        '<div class="home-kicker">GREATING SEARCH</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="home-title">Search Insight Dashboard 🔎</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="home-caption">'
        '그리팅몰 내부 검색과 외부 식품 검색 트렌드를 한 곳에서 확인합니다.'
        '</div>',
        unsafe_allow_html=True,
    )

with action:
    if st.button(
        "로그아웃",
        use_container_width=True,
        key="home_logout",
    ):
        logout()

st.markdown("### 대시보드 선택")

c1, c2 = st.columns(2, gap="large")

with c1:
    st.markdown(
        """
        <div class="nav-card">
          <div class="nav-card-title">🔎 GREATING SEARCH</div>
          <div class="nav-card-desc">
            GA4 기반 그리팅몰 내부 검색어. 분석기간, 전일·전주·4주평균·Custom 비교와 검색어 Top 50을 확인합니다.
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="nav-button-spacer"></div>',
        unsafe_allow_html=True,
    )
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
          <div class="nav-card-desc">
            NAVER 데이터랩 식품 인기검색어 TOP 500 누적 데이터. 식품 전체와 세부분류별 순위, 전년 비교, 급상승·급락과 추이를 확인합니다.
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="nav-button-spacer"></div>',
        unsafe_allow_html=True,
    )
    if st.button(
        "🔥 네이버 검색 트렌드 보기",
        use_container_width=True,
        key="home_naver_food_trend",
    ):
        st.switch_page("pages/02_NAVER_Food_Trend.py")


st.markdown("---")
st.markdown("### NAVER 데이터 관리")

KST = ZoneInfo("Asia/Seoul")
today_kst = datetime.now(KST).date()
target_date = today_kst - timedelta(days=1)

try:
    meta_df = load_naver_food_meta()

    if meta_df.empty:
        latest_complete_date = None
    else:
        scope_counts = (
            meta_df.groupby("snapshot_date")["scope_key"]
            .nunique()
            .sort_index()
        )
        complete_dates = scope_counts[
            scope_counts >= 4
        ].index.tolist()
        latest_complete_date = (
            max(complete_dates)
            if complete_dates
            else None
        )
except Exception:
    latest_complete_date = None

status_label = "최신"
if latest_complete_date is None:
    status_label = "확인 필요"
elif latest_complete_date < target_date:
    status_label = "적재 필요"

m1, m2, m3 = st.columns(3)

with m1:
    st.metric(
        "최신 적재일",
        (
            latest_complete_date.strftime("%Y.%m.%d")
            if latest_complete_date
            else "-"
        ),
    )

with m2:
    st.metric(
        "오늘 적재 대상",
        target_date.strftime("%Y.%m.%d"),
    )

with m3:
    st.metric(
        "수집 상태",
        status_label,
    )

st.markdown(
    """
    <div class="data-admin-card">
      <div class="data-admin-title">🔄 D-1 데이터 수동 적재</div>
      <div class="data-admin-desc">
        평상시에는 GitHub Actions가 매일 아침 자동 적재합니다.
        자동 적재가 늦거나 재확인이 필요할 때만 아래 버튼을 사용하세요.
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

if st.button(
    "🔄 D-1 데이터 적재",
    use_container_width=True,
    type="primary",
    key="home_naver_d1_load",
):
    with st.spinner(
        f"{target_date.strftime('%Y-%m-%d')} NAVER 데이터를 수집하고 있습니다..."
    ):
        try:
            result = run_manual(
                target_date.isoformat(),
                replace=False,
            )

            # 방금 적재한 META가 즉시 화면에 반영되도록 cache refresh.
            try:
                load_naver_food_meta.clear()
            except Exception:
                pass

            if result.get("WAIT", 0) > 0:
                st.warning(
                    "NAVER가 D-1 데이터를 아직 게시하지 않았습니다. "
                    "데이터는 NO_DATA로 확정하지 않았으므로 나중에 다시 실행하면 됩니다."
                )
            elif result.get("SUCCESS", 0) > 0:
                st.success(
                    f"{target_date.strftime('%Y-%m-%d')} 적재 완료 "
                    f"(신규 {result.get('SUCCESS', 0)}개 분류 / "
                    f"기존 {result.get('SKIP', 0)}개 분류)"
                )
            else:
                st.info(
                    f"{target_date.strftime('%Y-%m-%d')} 데이터는 이미 적재되어 있습니다."
                )

        except Exception as exc:
            st.error(
                "NAVER 데이터 적재 중 오류가 발생했습니다."
            )
            st.exception(exc)


render_footer(
    f"Greating Search Dashboard v{APP_VERSION}"
)
