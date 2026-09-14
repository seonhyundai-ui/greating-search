from __future__ import annotations

from datetime import timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

from src.app_auth import render_footer, require_authenticated

from src.naver_food_dashboard import (
    available_dates,
    build_top_table,
    format_rank_change,
    keyword_history,
    load_naver_food_history,
    rank_map,
    snapshot,
)

APP_VERSION = "0.1.3"
RANK_JUMP_THRESHOLD = 20


st.set_page_config(
    page_title="NAVER FOOD TREND",
    page_icon="🔥",
    layout="wide",
)


st.markdown(
    """
    <style>
    .block-container {
        max-width: 1500px;
        padding-top: 1.7rem;
        padding-bottom: 3rem;
    }

    .page-kicker {
        font-size: 0.83rem;
        font-weight: 800;
        letter-spacing: 0.08em;
        color: #107C41;
        margin-bottom: 0.25rem;
    }

    .page-title {
        font-size: 2.0rem;
        line-height: 1.25;
        font-weight: 850;
        margin: 0;
    }

    .page-subtitle {
        color: #667085;
        font-size: 0.95rem;
        margin-top: 0.45rem;
        margin-bottom: 1.35rem;
    }

    .section-title {
        font-size: 1.15rem;
        font-weight: 800;
        margin: 0.15rem 0 0.25rem 0;
    }

    .section-caption {
        color: #667085;
        font-size: 0.84rem;
        margin-bottom: 0.8rem;
    }

    .metric-note {
        color: #667085;
        font-size: 0.78rem;
    }

    .summary-card {
        border: 1px solid #EAECF0;
        border-radius: 12px;
        padding: 0.9rem 1rem;
        background: #FFFFFF;
        min-height: 128px;
    }
    .summary-label {
        color: #475467;
        font-size: 0.80rem;
        font-weight: 700;
        margin-bottom: 0.35rem;
    }
    .summary-value {
        color: #101828;
        font-size: 1.55rem;
        line-height: 1.2;
        font-weight: 800;
        margin-bottom: 0.55rem;
    }
    .summary-meta {
        color: #98A2B3;
        font-size: 0.72rem;
        line-height: 1.45;
    }

    div[data-testid="stMetric"] {
        border: 1px solid #EAECF0;
        border-radius: 12px;
        padding: 0.9rem 1rem;
        background: #FFFFFF;
    }

    div[data-testid="stDataFrame"] {
        border: 1px solid #EAECF0;
        border-radius: 12px;
        overflow: hidden;
    }
    </style>
    """,
    unsafe_allow_html=True,
)



def change_label(previous_rank, current_rank) -> str:
    return format_rank_change(previous_rank, current_rank)


def change_color(value: str) -> str:
    text = str(value)

    if text == "신규":
        return "color: #175CD3; background-color: #EFF8FF; font-weight: 700;"
    if text.startswith("▲"):
        return "color: #067647; background-color: #ECFDF3; font-weight: 700;"
    if text.startswith("▼"):
        return "color: #B42318; background-color: #FEF3F2; font-weight: 700;"
    return "color: #667085;"


def previous_year_date(value):
    """Return same calendar date one year earlier. Feb 29 -> Feb 28."""
    try:
        return value.replace(year=value.year - 1)
    except ValueError:
        return value.replace(year=value.year - 1, day=28)


def render_change_table(df: pd.DataFrame, height: int = 610) -> None:
    if df.empty:
        st.info("표시할 데이터가 없습니다.")
        return

    display_df = df.copy()
    for column in ("순위", "전일 순위", "전주 순위"):
        display_df[column] = display_df[column].apply(
            lambda x: "-" if pd.isna(x) else f"{int(x):,}"
        )

    styled = display_df.style.map(
        change_color,
        subset=["전일 대비", "전주 대비"],
    )

    st.dataframe(
        styled,
        use_container_width=True,
        hide_index=True,
        height=height,
        column_config={
            "순위": st.column_config.TextColumn(width="small"),
            "검색어": st.column_config.TextColumn(width="large"),
            "전일 순위": st.column_config.TextColumn(width="small"),
            "전일 대비": st.column_config.TextColumn(width="small"),
            "전주 순위": st.column_config.TextColumn(width="small"),
            "전주 대비": st.column_config.TextColumn(width="small"),
        },
    )


require_authenticated()

st.markdown('<div class="page-kicker">NAVER FOOD TREND</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="page-title">네이버에서 지금 무엇을 찾고 있을까? 🔎</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="page-subtitle">'
    'NAVER 데이터랩 쇼핑인사이트 「식품」 인기검색어 TOP 500 스냅샷 기반'
    '</div>',
    unsafe_allow_html=True,
)

left, right = st.columns([3.2, 1.0])

with right:
    if st.button("↻ 데이터 새로고침", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

try:
    history_df = load_naver_food_history()
except Exception as exc:
    st.error("Google Sheets의 NAVER 식품 검색어 데이터를 불러오지 못했습니다.")
    st.exception(exc)
    st.stop()

dates = available_dates(history_df)

if not dates:
    st.warning("NAVER_FOOD_KEYWORD_RAW에 적재된 데이터가 없습니다.")
    st.stop()

min_date = min(dates)
max_date = max(dates)

with st.container(border=True):
    c1, c2 = st.columns([1.15, 3.85])

    with c1:
        analysis_date = st.date_input(
            "분석일",
            value=max_date,
            min_value=min_date,
            max_value=max_date,
        )

    with c2:
        st.markdown("<div style='height: 1.8rem;'></div>", unsafe_allow_html=True)
        st.caption(
            f"적재 기간 {min_date.isoformat()} ~ {max_date.isoformat()} · "
            f"급상승/급락 기준 ±{RANK_JUMP_THRESHOLD}위"
        )

if analysis_date not in dates:
    st.warning(
        f"{analysis_date.isoformat()} 데이터가 아직 적재되지 않았습니다. "
        "다른 분석일을 선택해 주세요."
    )
    st.stop()

current = snapshot(history_df, analysis_date)
prev_day_date = analysis_date - timedelta(days=1)
prev_week_date = analysis_date - timedelta(days=7)
prev_year_date = previous_year_date(analysis_date)

prev_day_available = prev_day_date in dates
prev_week_available = prev_week_date in dates
prev_year_available = prev_year_date in dates

prev_day_map = rank_map(history_df, prev_day_date) if prev_day_available else {}
prev_week_map = rank_map(history_df, prev_week_date) if prev_week_available else {}
prev_year_map = rank_map(history_df, prev_year_date) if prev_year_available else {}

top_table = build_top_table(
    history_df,
    analysis_date=analysis_date,
    top_n=500,
)

top1_keyword = (
    str(current.iloc[0]["keyword"])
    if not current.empty
    else "-"
)

new_top500_count = (
    int(top_table["전일 순위"].isna().sum())
    if prev_day_available
    else 0
)

rise_top500_count = (
    int((top_table["전일 변동"].fillna(0) >= RANK_JUMP_THRESHOLD).sum())
    if prev_day_available
    else 0
)

fall_top500_count = (
    int((top_table["전일 변동"].fillna(0) <= -RANK_JUMP_THRESHOLD).sum())
    if prev_day_available
    else 0
)

m1, m2, m3, m4 = st.columns(4)

change_period = f"{prev_day_date.isoformat()} → {analysis_date.isoformat()}"

with m1:
    st.markdown(
        f"""
        <div class="summary-card">
            <div class="summary-label">🥇 1위 검색어</div>
            <div class="summary-value">{top1_keyword}</div>
            <div class="summary-meta">기준일 {analysis_date.isoformat()}<br>변경시점 {change_period}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with m2:
    new_value = f"{new_top500_count}개" if prev_day_available else "-"
    st.markdown(
        f"""
        <div class="summary-card">
            <div class="summary-label">신규 진입 · TOP500</div>
            <div class="summary-value">{new_value}</div>
            <div class="summary-meta">기준일 {analysis_date.isoformat()}<br>변경시점 {change_period}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with m3:
    rise_value = f"{rise_top500_count}개" if prev_day_available else "-"
    st.markdown(
        f"""
        <div class="summary-card">
            <div class="summary-label">급상승 · +{RANK_JUMP_THRESHOLD}위↑</div>
            <div class="summary-value">{rise_value}</div>
            <div class="summary-meta">기준일 {analysis_date.isoformat()}<br>변경시점 {change_period}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with m4:
    fall_value = f"{fall_top500_count}개" if prev_day_available else "-"
    st.markdown(
        f"""
        <div class="summary-card">
            <div class="summary-label">급락 · -{RANK_JUMP_THRESHOLD}위↓</div>
            <div class="summary-value">{fall_value}</div>
            <div class="summary-meta">기준일 {analysis_date.isoformat()}<br>변경시점 {change_period}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.markdown("")

left_panel, right_panel = st.columns([1.55, 1.0])

with left_panel:
    st.markdown(
        f'<div class="section-title">{analysis_date.isoformat()} 식품 인기검색어 TOP 500</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="section-caption">'
        '전일·전주 TOP 500 내 순위를 기준으로 변화를 표시합니다.'
        '</div>',
        unsafe_allow_html=True,
    )

    display = top_table.copy()
    display["전일 대비"] = display.apply(
        lambda r: change_label(r["전일 순위"], r["rank"])
        if prev_day_available
        else "-",
        axis=1,
    )
    display["전주 대비"] = display.apply(
        lambda r: change_label(r["전주 순위"], r["rank"])
        if prev_week_available
        else "-",
        axis=1,
    )

    display = display.rename(
        columns={
            "rank": "순위",
            "keyword": "검색어",
        }
    )[
        [
            "순위",
            "검색어",
            "전일 순위",
            "전일 대비",
            "전주 순위",
            "전주 대비",
        ]
    ]

    render_change_table(display)

with right_panel:
    st.markdown(
        '<div class="section-title">전년 대비 순위 변화</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="section-caption">'
        f'{prev_year_date.isoformat()} 동일일 대비 TOP500 순위 변화'
        '</div>',
        unsafe_allow_html=True,
    )

    yoy = current.copy()
    yoy["전년 순위"] = yoy["keyword"].map(prev_year_map)

    if prev_year_available:
        yoy["전년 대비"] = yoy.apply(
            lambda r: "신규"
            if pd.isna(r["전년 순위"])
            else (
                f"▲ {int(r['전년 순위']) - int(r['rank'])}"
                if int(r["전년 순위"]) - int(r["rank"]) > 0
                else (
                    f"▼ {abs(int(r['전년 순위']) - int(r['rank']))}"
                    if int(r["전년 순위"]) - int(r["rank"]) < 0
                    else "유지"
                )
            ),
            axis=1,
        )
    else:
        yoy["전년 대비"] = "-"

    yoy = (
        yoy.sort_values("rank")
        .rename(
            columns={
                "rank": "현재 순위",
                "keyword": "검색어",
            }
        )
    )

    yoy_display = yoy[
        ["현재 순위", "검색어", "전년 순위", "전년 대비"]
    ].copy()

    yoy_display["현재 순위"] = yoy_display["현재 순위"].apply(
        lambda x: "-" if pd.isna(x) else f"{int(x):,}"
    )
    yoy_display["전년 순위"] = yoy_display["전년 순위"].apply(
        lambda x: "-" if pd.isna(x) else f"{int(x):,}"
    )

    if not prev_year_available:
        st.info(
            f"{prev_year_date.isoformat()} 데이터가 아직 적재되지 않아 "
            "전년 대비 값은 '-'로 표시합니다."
        )

    yoy_styled = yoy_display.style.map(
        change_color,
        subset=["전년 대비"],
    )

    st.dataframe(
        yoy_styled,
        use_container_width=True,
        hide_index=True,
        height=610,
        column_config={
            "현재 순위": st.column_config.TextColumn(width="small"),
            "검색어": st.column_config.TextColumn(width="medium"),
            "전년 순위": st.column_config.TextColumn(width="small"),
            "전년 대비": st.column_config.TextColumn(width="small"),
        },
    )

st.markdown("")
tab1, tab2, tab3 = st.tabs(
    ["📈 검색어 30일 추이", "🔥 급상승 / 급락", "🚪 TOP500 이탈"]
)

with tab1:
    current_keywords = current.sort_values("rank")["keyword"].tolist()

    search_col, info_col = st.columns([1.5, 2.5])

    with search_col:
        selected_keyword = st.selectbox(
            "검색어 선택",
            options=current_keywords,
            index=0 if current_keywords else None,
            help="분석일 TOP500 검색어 중 하나를 선택하세요.",
        )

    if selected_keyword:
        keyword_df = keyword_history(
            history_df,
            keyword=selected_keyword,
            end_date=analysis_date,
            days=30,
        )

        current_rank_row = current[current["keyword"] == selected_keyword]
        current_rank = (
            int(current_rank_row.iloc[0]["rank"])
            if not current_rank_row.empty
            else None
        )

        with info_col:
            st.caption(
                f"{selected_keyword} · "
                f"{analysis_date.isoformat()} "
                f"{current_rank}위"
                if current_rank is not None
                else f"{selected_keyword} · 분석일 TOP500 밖"
            )

        fig = px.line(
            keyword_df,
            x="snapshot_date",
            y="display_rank",
            markers=True,
            custom_data=["status"],
        )
        fig.update_traces(
            hovertemplate="%{x}<br>%{customdata[0]}<extra></extra>"
        )
        fig.update_yaxes(
            autorange="reversed",
            title="순위",
            range=[min(505, max(60, float(keyword_df["display_rank"].max()) + 5)), 1],
        )
        fig.update_xaxes(title="")
        fig.update_layout(
            height=420,
            margin=dict(l=20, r=20, t=20, b=20),
            hovermode="x unified",
        )
        st.plotly_chart(fig, use_container_width=True)

        st.caption("※ TOP500 밖인 날짜는 차트에서 501위로 표시합니다.")

with tab2:
    if not prev_day_available:
        st.info(f"{prev_day_date.isoformat()} 데이터가 없어 급상승/급락을 계산할 수 없습니다.")
    else:
        compare = current.copy()
        compare["전일 순위"] = compare["keyword"].map(prev_day_map)
        compare = compare.dropna(subset=["전일 순위"]).copy()
        compare["순위 변동"] = (
            compare["전일 순위"].astype(int) - compare["rank"].astype(int)
        )

        rise = (
            compare[compare["순위 변동"] >= RANK_JUMP_THRESHOLD]
            .sort_values("순위 변동", ascending=False)
            .rename(columns={"rank": "현재 순위", "keyword": "검색어"})
        )
        fall = (
            compare[compare["순위 변동"] <= -RANK_JUMP_THRESHOLD]
            .sort_values("순위 변동", ascending=True)
            .rename(columns={"rank": "현재 순위", "keyword": "검색어"})
        )

        rc1, rc2 = st.columns(2)

        with rc1:
            st.markdown(f"#### 급상승 · {RANK_JUMP_THRESHOLD}위 이상")
            rise_display = rise[
                ["검색어", "현재 순위", "전일 순위", "순위 변동"]
            ].copy()
            rise_display["변화"] = rise_display["순위 변동"].apply(
                lambda x: f"▲ {int(x)}"
            )
            rise_display = rise_display.drop(columns=["순위 변동"])
            rise_display["현재 순위"] = rise_display["현재 순위"].apply(
                lambda x: "-" if pd.isna(x) else f"{int(x):,}"
            )
            rise_display["전일 순위"] = rise_display["전일 순위"].apply(
                lambda x: "-" if pd.isna(x) else f"{int(x):,}"
            )
            st.dataframe(
                rise_display.style.map(change_color, subset=["변화"]),
                use_container_width=True,
                hide_index=True,
                height=420,
                column_config={
                    "검색어": st.column_config.TextColumn(width="large"),
                    "현재 순위": st.column_config.TextColumn(width="small"),
                    "전일 순위": st.column_config.TextColumn(width="small"),
                    "변화": st.column_config.TextColumn(width="small"),
                },
            )

        with rc2:
            st.markdown(f"#### 급락 · {RANK_JUMP_THRESHOLD}위 이상")
            fall_display = fall[
                ["검색어", "현재 순위", "전일 순위", "순위 변동"]
            ].copy()
            fall_display["변화"] = fall_display["순위 변동"].apply(
                lambda x: f"▼ {abs(int(x))}"
            )
            fall_display = fall_display.drop(columns=["순위 변동"])
            fall_display["현재 순위"] = fall_display["현재 순위"].apply(
                lambda x: "-" if pd.isna(x) else f"{int(x):,}"
            )
            fall_display["전일 순위"] = fall_display["전일 순위"].apply(
                lambda x: "-" if pd.isna(x) else f"{int(x):,}"
            )
            st.dataframe(
                fall_display.style.map(change_color, subset=["변화"]),
                use_container_width=True,
                hide_index=True,
                height=420,
                column_config={
                    "검색어": st.column_config.TextColumn(width="large"),
                    "현재 순위": st.column_config.TextColumn(width="small"),
                    "전일 순위": st.column_config.TextColumn(width="small"),
                    "변화": st.column_config.TextColumn(width="small"),
                },
            )

with tab3:
    if not prev_day_available:
        st.info(f"{prev_day_date.isoformat()} 데이터가 없어 이탈 검색어를 계산할 수 없습니다.")
    else:
        current_map = rank_map(history_df, analysis_date)
        prev_day_snapshot = snapshot(history_df, prev_day_date)

        dropped = prev_day_snapshot[
            ~prev_day_snapshot["keyword"].isin(current_map.keys())
        ].copy()

        dropped = (
            dropped.sort_values("rank")
            .rename(columns={"rank": "전일 순위", "keyword": "검색어"})
        )

        st.caption(
            f"{prev_day_date.isoformat()}에는 TOP500이었지만 "
            f"{analysis_date.isoformat()} TOP500에서 사라진 검색어"
        )

        dropped_display = dropped[["전일 순위", "검색어"]].head(500).copy()
        dropped_display["전일 순위"] = dropped_display["전일 순위"].apply(
            lambda x: "-" if pd.isna(x) else f"{int(x):,}"
        )

        st.dataframe(
            dropped_display,
            use_container_width=True,
            hide_index=True,
            height=420,
            column_config={
                "전일 순위": st.column_config.TextColumn(width="small"),
                "검색어": st.column_config.TextColumn(width="large"),
            },
        )

st.caption(
    "원천: NAVER 데이터랩 쇼핑인사이트 식품 인기검색어 스냅샷"
)

render_footer(f"NAVER FOOD TREND v{APP_VERSION}")
