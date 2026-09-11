from __future__ import annotations

import hmac
from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

from src.ga4_search import (
    aggregate_average,
    comparison_dates,
    fetch_search_terms,
)


APP_VERSION = "0.1.3"
APP_TITLE = "DAILY SEARCH | 고객이 새롭게 찾고 있는 건 뭘까? 🔎"


st.set_page_config(
    page_title="Greating Daily Search",
    page_icon="🔎",
    layout="wide",
    initial_sidebar_state="collapsed",
)


st.markdown(
    """
    <style>
    .block-container {
        max-width: 1600px;
        padding-top: 1.55rem;
        padding-bottom: 3rem;
    }

    [data-testid="stSidebar"] {
        display: none;
    }

    .main-title {
        font-size: 1.62rem;
        line-height: 1.2;
        font-weight: 850;
        letter-spacing: -0.04em;
        margin: 0 0 0.3rem 0;
        color: #151b26;
    }

    .main-caption {
        color: #8a94a5;
        font-size: 0.83rem;
        margin-bottom: 1rem;
    }

    .control-card-note {
        color: #667085;
        font-size: 0.78rem;
    }

    div[data-testid="stVerticalBlockBorderWrapper"] {
        border-color: #d9dde4;
        border-radius: 10px;
        background: #ffffff;
        padding: 0.55rem 0.75rem 0.75rem 0.75rem;
    }

    .section-title {
        font-size: 1.15rem;
        font-weight: 800;
        letter-spacing: -0.025em;
        margin-top: 0.25rem;
        margin-bottom: 0.1rem;
    }

    .section-caption {
        color: #8a94a5;
        font-size: 0.76rem;
        margin-bottom: 0.6rem;
    }

    .badge-row {
        display: flex;
        flex-wrap: wrap;
        gap: 0.45rem;
        margin: 0.2rem 0 0.8rem 0;
    }

    .badge {
        display: inline-flex;
        align-items: center;
        border: 1px solid #e1e5ea;
        background: #f7f9fb;
        border-radius: 999px;
        padding: 0.38rem 0.72rem;
        color: #637083;
        font-size: 0.76rem;
    }

    .badge b {
        color: #1d2a3a;
        margin-left: 0.25rem;
    }

    div[data-testid="stButton"] > button[kind="primary"] {
        background: #ff4b55;
        border-color: #ff4b55;
        font-weight: 750;
    }

    div[data-testid="stButton"] > button {
        border-radius: 8px;
        min-height: 2.6rem;
    }

    div[data-testid="stDateInput"] input,
    div[data-testid="stTextInput"] input {
        background: #f2f4f7;
        border-radius: 7px;
    }


    .control-label {
        color: #475467;
        font-size: 0.78rem;
        font-weight: 600;
        line-height: 1.1;
        margin-bottom: 0.38rem;
        min-height: 0.95rem;
    }

    .button-label {
        visibility: hidden;
    }

    .search-panel-offset {
        height: 4.15rem;
    }

    .plot-caption-space {
        height: 0.1rem;
    }

    div[data-testid="stDataFrame"] {
        border: 1px solid #e2e6ec;
        border-radius: 8px;
        overflow: hidden;
    }

    #MainMenu, footer, header {
        visibility: hidden;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def _app_password() -> str:
    try:
        return str(st.secrets.get("APP_PASSWORD", "")).strip()
    except Exception:
        return ""


def check_password() -> bool:
    if st.session_state.get("authenticated") is True:
        return True

    st.markdown(
        '<div class="main-title">Greating Search Insight 🔐</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="main-caption">접근 비밀번호를 입력해주세요.</div>',
        unsafe_allow_html=True,
    )

    password = st.text_input(
        "비밀번호",
        type="password",
        label_visibility="collapsed",
        placeholder="비밀번호",
    )

    if st.button(
        "로그인",
        type="primary",
        use_container_width=True,
    ):
        expected = _app_password()

        if not expected:
            st.error("APP_PASSWORD가 설정되지 않았습니다.")
            return False

        if hmac.compare_digest(password, expected):
            st.session_state["authenticated"] = True
            st.rerun()

        st.error("비밀번호가 올바르지 않습니다.")

    return False


@st.cache_data(ttl=300, show_spinner=False)
def load_date_rows(target_date: str) -> list[dict]:
    return fetch_search_terms(target_date)


def _safe_total(rows: list[dict]) -> float:
    return sum(float(row["views"]) for row in rows)


def _format_count(value: float) -> str:
    return f"{value:,.0f}"


def _compare_label(mode: str) -> str:
    return {
        "전일": "전일",
        "전주": "전주",
        "4주평균": "4주평균",
        "Custom Date": "Custom Date",
    }[mode]


def _build_compare_dataframe(
    current_rows: list[dict],
    compare_rows: list[dict],
    compare_column_name: str,
) -> pd.DataFrame:
    current_map = {
        row["search_term"]: float(row["views"])
        for row in current_rows
    }
    compare_map = {
        row["search_term"]: float(row["views"])
        for row in compare_rows
    }

    current_total = sum(current_map.values())

    records = []

    for term, current_views in current_map.items():
        compare_views = compare_map.get(term, 0.0)

        if compare_views > 0:
            change_rate = (
                current_views - compare_views
            ) / compare_views
        elif current_views > 0:
            change_rate = None
        else:
            change_rate = 0.0

        share = (
            current_views / current_total
            if current_total > 0
            else 0.0
        )

        records.append(
            {
                "검색어": term,
                "현재 조회수": current_views,
                compare_column_name: compare_views,
                "증감률": change_rate,
                "현재 비중": share,
            }
        )

    df = pd.DataFrame(records)

    if df.empty:
        return df

    return df.sort_values(
        by="현재 조회수",
        ascending=False,
    ).reset_index(drop=True)


def _format_change(value) -> str:
    if pd.isna(value):
        return "신규"

    arrow = "▲" if value > 0 else "▼" if value < 0 else "→"
    return f"{arrow} {abs(value) * 100:.1f}%"


def _change_style(value: str) -> str:
    if value == "신규":
        return "color:#175CD3;background-color:#EFF8FF;font-weight:700;"

    if str(value).startswith("▲"):
        return "color:#079447;background-color:#edf8f1;font-weight:700;"

    if str(value).startswith("▼"):
        return "color:#f04438;background-color:#fff2f1;font-weight:700;"

    return "color:#667085;font-weight:700;"


if not check_password():
    st.stop()


header_left, header_right = st.columns([5.7, 1.0])

with header_left:
    st.markdown(
        f'<div class="main-title">{APP_TITLE}</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="main-caption">GA4 검색 데이터를 직접 조회해 분석일과 선택 기준일의 검색 흐름을 비교합니다.</div>',
        unsafe_allow_html=True,
    )

with header_right:
    if st.button(
        "↻ 데이터 새로고침",
        use_container_width=True,
    ):
        st.cache_data.clear()
        st.session_state.pop("search_result", None)
        st.rerun()


with st.container(border=True):
    c1, c2, c3, c4 = st.columns([1.25, 2.2, 1.35, 1.0])

    with c1:
        analysis_date = st.date_input(
            "분석일",
            value=date.today() - timedelta(days=1),
            max_value=date.today(),
            format="YYYY/MM/DD",
        )

    with c2:
        compare_mode = st.radio(
            "비교 기준",
            options=["전일", "전주", "4주평균", "Custom Date"],
            horizontal=True,
        )

    with c3:
        default_custom = analysis_date - timedelta(days=30)
        custom_date = st.date_input(
            "Custom Date",
            value=default_custom,
            max_value=date.today(),
            disabled=compare_mode != "Custom Date",
            format="YYYY/MM/DD",
        )

    with c4:
        st.markdown("<div class='control-label button-label'>조회 실행</div>", unsafe_allow_html=True)
        query_clicked = st.button(
            "GA4 조회",
            type="primary",
            use_container_width=True,
        )


if query_clicked:
    compare_dates = comparison_dates(
        target_date=analysis_date,
        compare_mode=compare_mode,
        custom_date=custom_date,
    )

    if analysis_date in compare_dates:
        st.error("분석일과 비교일은 서로 달라야 합니다.")
        st.stop()

    try:
        with st.spinner("GA4 검색 데이터를 조회하고 있습니다..."):
            current_rows = load_date_rows(analysis_date.isoformat())
            compare_datasets = [
                load_date_rows(day.isoformat())
                for day in compare_dates
            ]

            available_datasets = [
                rows
                for rows in compare_datasets
                if rows
            ]

            if compare_mode == "4주평균":
                compare_rows = aggregate_average(available_datasets)
            else:
                compare_rows = (
                    available_datasets[0]
                    if available_datasets
                    else []
                )

        st.session_state["search_result"] = {
            "analysis_date": analysis_date.isoformat(),
            "compare_mode": compare_mode,
            "compare_dates": [day.isoformat() for day in compare_dates],
            "custom_date": custom_date.isoformat(),
            "current_rows": current_rows,
            "compare_rows": compare_rows,
            "available_count": len(available_datasets),
        }

    except Exception as error:
        st.error("GA4 검색 데이터 조회 중 오류가 발생했습니다.")
        st.code(str(error))
        st.stop()


result = st.session_state.get("search_result")

if result is None:
    st.info("분석일과 비교 기준을 선택한 뒤 **GA4 조회**를 눌러주세요.")
    st.stop()


current_rows = result["current_rows"]
compare_rows = result["compare_rows"]
current_total = _safe_total(current_rows)
compare_total = _safe_total(compare_rows)
compare_mode_result = result["compare_mode"]
compare_dates_result = result["compare_dates"]

if compare_mode_result == "4주평균":
    compare_date_text = " / ".join(compare_dates_result)
    compare_column_name = "4주 평균 조회수"
else:
    compare_date_text = compare_dates_result[0]
    compare_column_name = f"{_compare_label(compare_mode_result)} 조회수"

st.markdown(
    f"""
    <div class="badge-row">
      <span class="badge">분석일 <b>{result['analysis_date']}</b></span>
      <span class="badge">비교 <b>{_compare_label(compare_mode_result)}</b></span>
      <span class="badge">현재 조회수 <b>{_format_count(current_total)}</b></span>
      <span class="badge">비교 조회수 <b>{_format_count(compare_total)}</b></span>
      <span class="badge">비교 날짜 <b>{compare_date_text}</b></span>
    </div>
    """,
    unsafe_allow_html=True,
)

if compare_mode_result == "4주평균" and result["available_count"] < 4:
    st.warning(
        "4주 비교일 중 데이터가 존재하는 날짜만 평균에 사용했습니다. "
        f"사용 가능 {result['available_count']}/4일"
    )

if not current_rows:
    st.warning("선택한 분석일에 표시 가능한 검색어 데이터가 없습니다.")
    st.stop()

left, right = st.columns([1.05, 1.9], gap="large")

with left:
    with st.container(border=True):
        st.markdown(
            '<div class="section-title">검색어 Top 50</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="section-caption">분석일 조회수 상위 50개 검색어입니다.</div>',
            unsafe_allow_html=True,
        )
        st.markdown("<div class='search-panel-offset'></div>", unsafe_allow_html=True)

        treemap_df = pd.DataFrame(current_rows[:50]).rename(
            columns={
                "search_term": "검색어",
                "views": "검색량",
            }
        )

        fig = px.treemap(
            treemap_df,
            path=[px.Constant("검색어"), "검색어"],
            values="검색량",
            color="검색량",
            color_continuous_scale=[
                "#eff8ec",
                "#cdebc4",
                "#93d188",
                "#3e9b59",
                "#005522",
            ],
        )

        fig.update_traces(
            root_color="white",
            texttemplate="<b>%{label}</b><br>%{value:,.0f}",
            hovertemplate=(
                "<b>%{label}</b><br>"
                "조회수 %{value:,.0f}"
                "<extra></extra>"
            ),
            marker=dict(line=dict(width=1, color="white")),
        )

        fig.update_layout(
            margin=dict(t=0, l=0, r=0, b=0),
            height=600,
            coloraxis_showscale=False,
            paper_bgcolor="white",
        )

        st.plotly_chart(
            fig,
            use_container_width=True,
            config={"displayModeBar": False},
        )

with right:
    with st.container(border=True):
        st.markdown(
            '<div class="section-title">검색어 기간 비교</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="section-caption">현재 조회수와 선택한 비교 기준 조회수를 비교합니다.</div>',
            unsafe_allow_html=True,
        )

        st.markdown('<div class="control-label">검색어 찾기</div>', unsafe_allow_html=True)
        keyword = st.text_input(
            "검색어 찾기",
            placeholder="검색어를 입력하세요",
            label_visibility="collapsed",
        )

        compare_df = _build_compare_dataframe(
            current_rows=current_rows,
            compare_rows=compare_rows,
            compare_column_name=compare_column_name,
        )

    if keyword.strip():
        compare_df = compare_df[
            compare_df["검색어"].str.contains(
                keyword.strip(),
                case=False,
                na=False,
            )
        ]

    display_df = compare_df.copy()

    if not display_df.empty:
        display_df["현재 조회수"] = display_df["현재 조회수"].round(0)
        display_df[compare_column_name] = display_df[compare_column_name].round(1)
        display_df["증감"] = display_df["증감률"].apply(_format_change)
        display_df["현재 비중"] = display_df["현재 비중"].map(
            lambda value: f"{value * 100:.2f}%"
        )

        display_df = display_df[
            [
                "검색어",
                "현재 조회수",
                compare_column_name,
                "증감",
                "현재 비중",
            ]
        ]

        styled_df = (
            display_df.style
            .format(
                {
                    "현재 조회수": "{:,.0f}",
                    compare_column_name: "{:,.1f}" if compare_mode_result == "4주평균" else "{:,.0f}",
                }
            )
            .map(_change_style, subset=["증감"])
        )

        st.dataframe(
            styled_df,
            use_container_width=True,
            hide_index=True,
            height=600,
        )
    else:
        st.info("조건에 맞는 검색어가 없습니다.")

st.caption(
    "검색량 기준: Web page_view + App screen_view의 screenPageViews · "
    "이메일/전화번호 등 개인정보 가능성이 높은 검색어는 화면에서 제외됩니다. "
    f"v{APP_VERSION}"
)
