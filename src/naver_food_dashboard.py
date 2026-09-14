from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from src.naver_spreadsheet_config import get_spreadsheet_ids

SHEET_NAME = "NAVER_FOOD_KEYWORD_RAW"
LOCAL_TOKEN_FILE = Path("token_sheets.json")

SCOPE_ORDER = [
    "FOOD_ALL",
    "FROZEN_CONVENIENCE",
    "MEALKIT",
    "INSTANT_RICE_SOUP",
]

SCOPE_NAMES = {
    "FOOD_ALL": "식품 전체",
    "FROZEN_CONVENIENCE": "냉동/간편조리식품",
    "MEALKIT": "밀키트",
    "INSTANT_RICE_SOUP": "즉석밥/즉석국",
}


def _cloud_credentials() -> Credentials | None:
    for section_name in (
        "google_sheets_oauth",
        "google_oauth",
    ):
        if section_name not in st.secrets:
            continue

        section = st.secrets[section_name]
        required = (
            "refresh_token",
            "token_uri",
            "client_id",
            "client_secret",
        )

        if not all(
            section.get(key)
            for key in required
        ):
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
            "로컬 token_sheets.json을 찾을 수 없습니다."
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
            "scope_key",
            "scope_name",
        ]
    )


def _load_one_spreadsheet(
    service,
    year: int,
    spreadsheet_id: str,
) -> pd.DataFrame:
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
        sheet.get("properties", {}).get(
            "title",
            "",
        )
        for sheet in metadata.get(
            "sheets",
            [],
        )
    }

    if SHEET_NAME not in sheet_titles:
        return _empty_frame()

    try:
        result = (
            service.spreadsheets()
            .values()
            .get(
                spreadsheetId=spreadsheet_id,
                range=f"'{SHEET_NAME}'!A:H",
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

    header = list(values[0])
    rows = values[1:]

    # 기존 A:F 6컬럼 시트도 읽을 수 있게 G/H 헤더를 가상 추가한다.
    expected = [
        "snapshot_date",
        "rank",
        "keyword",
        "category_id",
        "category_name",
        "collected_at",
        "scope_key",
        "scope_name",
    ]

    width = max(
        len(header),
        len(expected),
    )

    if len(header) < len(expected):
        header = header + expected[len(header):]

    normalized = []

    for row in rows:
        row = list(row) + [""] * (
            len(header) - len(row)
        )
        normalized.append(
            row[:len(header)]
        )

    df = pd.DataFrame(
        normalized,
        columns=header,
    )

    for column in expected:
        if column not in df.columns:
            df[column] = ""

    df = df[expected].copy()
    df["_source_year"] = year

    return df


@st.cache_data(
    ttl=300,
    show_spinner=False,
)
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

    df = pd.concat(
        frames,
        ignore_index=True,
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

    df["category_id"] = (
        df["category_id"]
        .astype(str)
        .str.strip()
    )

    df["scope_key"] = (
        df["scope_key"]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    df["scope_name"] = (
        df["scope_name"]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    # 기존 6컬럼 데이터는 식품 전체로 간주.
    legacy_food_mask = (
        (df["scope_key"] == "")
        & (df["category_id"] == "50000006")
    )

    df.loc[
        legacy_food_mask,
        "scope_key",
    ] = "FOOD_ALL"

    df.loc[
        legacy_food_mask,
        "scope_name",
    ] = "식품 전체"

    # 새 데이터인데 scope_name만 빈 경우 설정값으로 보완.
    for key, name in SCOPE_NAMES.items():
        mask = (
            (df["scope_key"] == key)
            & (df["scope_name"] == "")
        )

        df.loc[
            mask,
            "scope_name",
        ] = name

    df = df.dropna(
        subset=[
            "snapshot_date",
            "rank",
        ]
    )

    df = df[
        df["keyword"] != ""
    ].copy()

    df["rank"] = (
        df["rank"]
        .astype(int)
    )

    # 같은 날짜/분류/순위 중복 시 마지막 적재값 사용.
    df = (
        df.sort_values(
            [
                "snapshot_date",
                "scope_key",
                "rank",
                "collected_at",
            ]
        )
        .drop_duplicates(
            subset=[
                "snapshot_date",
                "scope_key",
                "rank",
            ],
            keep="last",
        )
        .reset_index(drop=True)
    )

    return df


def available_scopes(
    df: pd.DataFrame,
) -> list[tuple[str, str]]:
    if df.empty:
        return []

    present = set(
        df["scope_key"]
        .dropna()
        .astype(str)
        .tolist()
    )

    result = []

    for key in SCOPE_ORDER:
        if key in present:
            result.append(
                (
                    key,
                    SCOPE_NAMES[key],
                )
            )

    return result


def filter_scope(
    df: pd.DataFrame,
    scope_key: str,
) -> pd.DataFrame:
    return (
        df[
            df["scope_key"] == scope_key
        ]
        .copy()
        .reset_index(drop=True)
    )


def available_dates(
    df: pd.DataFrame,
) -> list:
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
        df[
            df["snapshot_date"] == target_date
        ]
        .sort_values("rank")
        .reset_index(drop=True)
        .copy()
    )


def rank_map(
    df: pd.DataFrame,
    target_date,
) -> dict[str, int]:
    day = snapshot(
        df,
        target_date,
    )

    return dict(
        zip(
            day["keyword"],
            day["rank"],
        )
    )


def build_top_table(
    df: pd.DataFrame,
    analysis_date,
    top_n: int = 500,
) -> pd.DataFrame:
    current = (
        snapshot(
            df,
            analysis_date,
        )
        .head(top_n)
        .copy()
    )

    if current.empty:
        return current

    from datetime import timedelta

    prev_day = (
        analysis_date
        - timedelta(days=1)
    )

    prev_week = (
        analysis_date
        - timedelta(days=7)
    )

    day_map = rank_map(
        df,
        prev_day,
    )

    week_map = rank_map(
        df,
        prev_week,
    )

    current["전일 순위"] = (
        current["keyword"]
        .map(day_map)
    )

    current["전주 순위"] = (
        current["keyword"]
        .map(week_map)
    )

    current["전일 변동"] = current.apply(
        lambda row: None
        if pd.isna(row["전일 순위"])
        else (
            int(row["전일 순위"])
            - int(row["rank"])
        ),
        axis=1,
    )

    current["전주 변동"] = current.apply(
        lambda row: None
        if pd.isna(row["전주 순위"])
        else (
            int(row["전주 순위"])
            - int(row["rank"])
        ),
        axis=1,
    )

    return current


def format_rank_change(
    previous_rank,
    current_rank,
) -> str:
    if pd.isna(previous_rank):
        return "신규"

    change = (
        int(previous_rank)
        - int(current_rank)
    )

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

    start_date = (
        end_date
        - timedelta(
            days=days - 1,
        )
    )

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
        & (
            df["snapshot_date"]
            >= start_date
        )
        & (
            df["snapshot_date"]
            <= end_date
        )
    ][
        [
            "snapshot_date",
            "rank",
        ]
    ].copy()

    history = dates.merge(
        subset,
        how="left",
        on="snapshot_date",
    )

    history["display_rank"] = (
        history["rank"]
        .fillna(501)
    )

    history["status"] = (
        history["rank"]
        .apply(
            lambda x: (
                "TOP500 밖"
                if pd.isna(x)
                else f"{int(x)}위"
            )
        )
    )

    return history
