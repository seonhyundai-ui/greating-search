from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from src.naver_spreadsheet_config import get_spreadsheet_ids

SHEET_NAME = "NAVER_FOOD_KEYWORD_RAW"
LOCAL_TOKEN_FILE = Path("token_sheets.json")


def _cloud_credentials() -> Credentials | None:
    """
    Streamlit Cloud에서는 Google Sheets 전용 OAuth를 우선 사용한다.
    token_sheets.json으로 발급한 refresh token 값을
    [google_sheets_oauth]에 넣는 것을 권장한다.
    """
    for section_name in ("google_sheets_oauth", "google_oauth"):
        if section_name not in st.secrets:
            continue

        section = st.secrets[section_name]
        required = (
            "refresh_token",
            "token_uri",
            "client_id",
            "client_secret",
        )

        if not all(section.get(key) for key in required):
            continue

        return Credentials(
            token=None,
            refresh_token=section["refresh_token"],
            token_uri=section["token_uri"],
            client_id=section["client_id"],
            client_secret=section["client_secret"],
        )

    return None


def get_sheets_read_credentials() -> Credentials:
    cloud = _cloud_credentials()

    if cloud is not None:
        return cloud

    if not LOCAL_TOKEN_FILE.exists():
        raise FileNotFoundError(
            "로컬 token_sheets.json을 찾을 수 없습니다. "
            "먼저 NAVER 수집/Sheets 적재 인증을 완료하세요."
        )

    return Credentials.from_authorized_user_file(
        str(LOCAL_TOKEN_FILE)
    )


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "snapshot_date",
            "rank",
            "keyword",
            "category_id",
            "category_name",
            "collected_at",
        ]
    )


def _load_one_spreadsheet(
    service,
    year: int,
    spreadsheet_id: str,
) -> pd.DataFrame:
    # 미래 연도 Spreadsheet를 미리 등록해두더라도
    # NAVER_FOOD_KEYWORD_RAW 탭이 아직 없다면 오류가 아니라 빈 연도로 건너뛴다.
    try:
        metadata = (
            service.spreadsheets()
            .get(
                spreadsheetId=spreadsheet_id,
                fields="sheets.properties(title)",
            )
            .execute()
        )
    except Exception as exc:
        raise RuntimeError(
            f"NAVER_SEARCH_{year} Spreadsheet에 접근하지 못했습니다. "
            "Spreadsheet ID 또는 Google 계정 권한을 확인하세요."
        ) from exc

    sheet_titles = {
        sheet.get("properties", {}).get("title", "")
        for sheet in metadata.get("sheets", [])
    }

    if SHEET_NAME not in sheet_titles:
        return _empty_frame()

    try:
        result = (
            service.spreadsheets()
            .values()
            .get(
                spreadsheetId=spreadsheet_id,
                range=f"'{SHEET_NAME}'!A:F",
            )
            .execute()
        )
    except Exception as exc:
        raise RuntimeError(
            f"NAVER_SEARCH_{year}의 {SHEET_NAME}을 읽지 못했습니다."
        ) from exc

    values = result.get("values", [])

    if len(values) <= 1:
        return _empty_frame()

    header = values[0]
    rows = values[1:]
    width = len(header)

    normalized = []
    for row in rows:
        row = list(row) + [""] * (width - len(row))
        normalized.append(row[:width])

    df = pd.DataFrame(normalized, columns=header)
    df["_source_year"] = year

    return df


@st.cache_data(ttl=300, show_spinner=False)
def load_naver_food_history() -> pd.DataFrame:
    creds = get_sheets_read_credentials()
    service = build(
        "sheets",
        "v4",
        credentials=creds,
        cache_discovery=False,
    )

    mapping = get_spreadsheet_ids()

    if not mapping:
        raise RuntimeError(
            "NAVER_SEARCH 연도별 Spreadsheet ID가 하나도 등록되지 않았습니다."
        )

    frames: list[pd.DataFrame] = []

    for year, spreadsheet_id in mapping.items():
        frame = _load_one_spreadsheet(
            service,
            year,
            spreadsheet_id,
        )

        if not frame.empty:
            frames.append(frame)

    if not frames:
        return _empty_frame()

    df = pd.concat(frames, ignore_index=True)

    required = {
        "snapshot_date",
        "rank",
        "keyword",
        "category_id",
        "category_name",
        "collected_at",
    }

    missing = required - set(df.columns)

    if missing:
        raise ValueError(
            "NAVER_FOOD_KEYWORD_RAW 컬럼이 예상과 다릅니다. "
            f"missing={sorted(missing)}"
        )

    df["snapshot_date"] = pd.to_datetime(
        df["snapshot_date"],
        errors="coerce",
    ).dt.date

    df["rank"] = pd.to_numeric(
        df["rank"],
        errors="coerce",
    )

    df["keyword"] = (
        df["keyword"]
        .astype(str)
        .str.strip()
    )

    df = df.dropna(
        subset=["snapshot_date", "rank"]
    )

    df = df[
        df["keyword"] != ""
    ].copy()

    df["rank"] = df["rank"].astype(int)

    df = (
        df.sort_values(
            ["snapshot_date", "rank", "collected_at"]
        )
        .drop_duplicates(
            subset=["snapshot_date", "rank"],
            keep="last",
        )
        .reset_index(drop=True)
    )

    return df


def available_dates(df: pd.DataFrame) -> list:
    if df.empty:
        return []

    return sorted(
        df["snapshot_date"]
        .dropna()
        .unique()
        .tolist()
    )


def snapshot(
    df: pd.DataFrame,
    target_date,
) -> pd.DataFrame:
    return (
        df[df["snapshot_date"] == target_date]
        .sort_values("rank")
        .reset_index(drop=True)
        .copy()
    )


def rank_map(
    df: pd.DataFrame,
    target_date,
) -> dict[str, int]:
    day = snapshot(df, target_date)
    return dict(
        zip(day["keyword"], day["rank"])
    )


def build_top_table(
    df: pd.DataFrame,
    analysis_date,
    top_n: int = 500,
) -> pd.DataFrame:
    current = (
        snapshot(df, analysis_date)
        .head(top_n)
        .copy()
    )

    if current.empty:
        return current

    from datetime import timedelta

    prev_day = analysis_date - timedelta(days=1)
    prev_week = analysis_date - timedelta(days=7)

    day_map = rank_map(df, prev_day)
    week_map = rank_map(df, prev_week)

    current["전일 순위"] = current["keyword"].map(day_map)
    current["전주 순위"] = current["keyword"].map(week_map)

    current["전일 변동"] = current.apply(
        lambda row: None
        if pd.isna(row["전일 순위"])
        else int(row["전일 순위"]) - int(row["rank"]),
        axis=1,
    )

    current["전주 변동"] = current.apply(
        lambda row: None
        if pd.isna(row["전주 순위"])
        else int(row["전주 순위"]) - int(row["rank"]),
        axis=1,
    )

    return current


def format_rank_change(
    previous_rank,
    current_rank,
) -> str:
    if pd.isna(previous_rank):
        return "신규"

    change = int(previous_rank) - int(current_rank)

    if change > 0:
        return f"▲ {change}"

    if change < 0:
        return f"▼ {abs(change)}"

    return "유지"


def keyword_history(
    df: pd.DataFrame,
    keyword: str,
    end_date,
    days: int = 30,
) -> pd.DataFrame:
    from datetime import timedelta

    start_date = end_date - timedelta(days=days - 1)

    dates = pd.DataFrame(
        {
            "snapshot_date": pd.date_range(
                start=start_date,
                end=end_date,
                freq="D",
            ).date
        }
    )

    subset = df[
        (df["keyword"] == keyword)
        & (df["snapshot_date"] >= start_date)
        & (df["snapshot_date"] <= end_date)
    ][["snapshot_date", "rank"]].copy()

    history = dates.merge(
        subset,
        how="left",
        on="snapshot_date",
    )

    history["display_rank"] = (
        history["rank"]
        .fillna(501)
    )

    history["status"] = history["rank"].apply(
        lambda x: "TOP500 밖"
        if pd.isna(x)
        else f"{int(x)}위"
    )

    return history
