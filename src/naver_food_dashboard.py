from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pandas as pd
import streamlit as st
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from src.naver_monthly_store import (
    DATA_HEADERS,
    META_HEADERS,
    META_SHEET,
    SCOPE_NAMES,
    SCOPE_ORDER,
)
from src.naver_spreadsheet_config import get_spreadsheet_ids

APP_VERSION = "0.4.0"
LOCAL_TOKEN_FILE = Path("token_sheets.json")


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


def _service():
    return build(
        "sheets",
        "v4",
        credentials=get_sheets_read_credentials(),
        cache_discovery=False,
    )


def _sheet_titles(
    service,
    spreadsheet_id: str,
) -> set[str]:
    result = (
        service.spreadsheets()
        .get(
            spreadsheetId=spreadsheet_id,
            fields="sheets.properties(title)",
        )
        .execute()
    )

    return {
        sheet.get("properties", {}).get("title", "")
        for sheet in result.get("sheets", [])
    }


@st.cache_data(
    ttl=300,
    show_spinner=False,
)
def load_naver_food_meta() -> pd.DataFrame:
    """
    대시보드 첫 로딩에서는 대용량 월별 데이터가 아니라
    연도별 NAVER_META만 읽는다.
    """
    service = _service()
    mapping = get_spreadsheet_ids()

    frames = []

    for year, spreadsheet_id in mapping.items():
        try:
            titles = _sheet_titles(
                service,
                spreadsheet_id,
            )
        except Exception as exc:
            raise RuntimeError(
                f"NAVER_SEARCH_{year} Spreadsheet에 접근하지 못했습니다."
            ) from exc

        if META_SHEET not in titles:
            continue

        values = (
            service.spreadsheets()
            .values()
            .get(
                spreadsheetId=spreadsheet_id,
                range=f"'{META_SHEET}'!A2:J",
            )
            .execute()
            .get("values", [])
        )

        rows = []

        for raw in values:
            row = list(raw) + [""] * (10 - len(raw))

            if not str(row[0]).strip():
                continue

            rows.append(row[:10])

        if not rows:
            continue

        frame = pd.DataFrame(
            rows,
            columns=META_HEADERS,
        )
        frame["_source_year"] = year
        frame["_spreadsheet_id"] = spreadsheet_id
        frames.append(frame)

    if not frames:
        return pd.DataFrame(
            columns=META_HEADERS
            + [
                "_source_year",
                "_spreadsheet_id",
            ]
        )

    meta = pd.concat(
        frames,
        ignore_index=True,
    )

    meta["snapshot_date"] = pd.to_datetime(
        meta["snapshot_date"],
        errors="coerce",
    ).dt.date

    for column in (
        "row_start",
        "row_end",
        "row_count",
    ):
        meta[column] = pd.to_numeric(
            meta[column],
            errors="coerce",
        )

    meta["scope_key"] = (
        meta["scope_key"]
        .astype(str)
        .str.strip()
    )

    meta["scope_name"] = (
        meta["scope_name"]
        .astype(str)
        .str.strip()
    )

    meta["status"] = (
        meta["status"]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    meta = meta.dropna(
        subset=["snapshot_date"]
    ).copy()

    return (
        meta.sort_values(
            [
                "snapshot_date",
                "scope_key",
            ]
        )
        .reset_index(drop=True)
    )


def available_scopes(
    meta_df: pd.DataFrame,
) -> list[tuple[str, str]]:
    if meta_df.empty:
        return []

    data_meta = meta_df[
        meta_df["status"] == "DATA"
    ]

    present = set(
        data_meta["scope_key"]
        .dropna()
        .tolist()
    )

    return [
        (
            key,
            SCOPE_NAMES[key],
        )
        for key in SCOPE_ORDER
        if key in present
    ]


def available_dates(
    meta_df: pd.DataFrame,
    scope_key: str,
) -> list:
    if meta_df.empty:
        return []

    subset = meta_df[
        (meta_df["scope_key"] == scope_key)
        & (meta_df["status"] == "DATA")
    ]

    return sorted(
        subset["snapshot_date"]
        .dropna()
        .unique()
        .tolist()
    )


def _previous_year_date(value):
    try:
        return value.replace(year=value.year - 1)
    except ValueError:
        return value.replace(
            year=value.year - 1,
            day=28,
        )


def _required_dates(
    analysis_date,
    history_days: int,
) -> set:
    start_date = (
        analysis_date
        - timedelta(days=history_days - 1)
    )

    dates = {
        start_date + timedelta(days=offset)
        for offset in range(history_days)
    }

    dates.add(
        _previous_year_date(
            analysis_date
        )
    )

    return dates


def _batch_get_records(
    service,
    spreadsheet_id: str,
    records: list[dict],
) -> list[pd.DataFrame]:
    if not records:
        return []

    ranges = [
        (
            f"'{record['sheet_name']}'!"
            f"A{int(record['row_start'])}:"
            f"F{int(record['row_end'])}"
        )
        for record in records
    ]

    result = (
        service.spreadsheets()
        .values()
        .batchGet(
            spreadsheetId=spreadsheet_id,
            ranges=ranges,
        )
        .execute()
    )

    value_ranges = result.get(
        "valueRanges",
        [],
    )

    frames = []

    for record, value_range in zip(
        records,
        value_ranges,
    ):
        values = value_range.get(
            "values",
            [],
        )

        if not values:
            continue

        normalized = [
            list(row) + [""] * (
                len(DATA_HEADERS) - len(row)
            )
            for row in values
        ]

        frame = pd.DataFrame(
            [
                row[:len(DATA_HEADERS)]
                for row in normalized
            ],
            columns=DATA_HEADERS,
        )

        frame["scope_key"] = record["scope_key"]
        frame["scope_name"] = record["scope_name"]
        frames.append(frame)

    return frames


@st.cache_data(
    ttl=300,
    show_spinner=False,
)
def load_naver_food_analysis_history(
    scope_key: str,
    analysis_date,
    history_days: int = 30,
) -> pd.DataFrame:
    """
    필요한 데이터만 읽는다.

    - 분석일 포함 최근 history_days
    - 전년도 동일일

    전일/전주 비교는 recent window 안에 포함되므로 별도 추가 조회가 없다.
    """
    meta = load_naver_food_meta()

    if meta.empty:
        return _empty_history()

    required = _required_dates(
        analysis_date,
        history_days,
    )

    selected = meta[
        (meta["scope_key"] == scope_key)
        & (meta["status"] == "DATA")
        & (meta["snapshot_date"].isin(required))
        & (meta["row_start"].notna())
        & (meta["row_end"].notna())
    ].copy()

    if selected.empty:
        return _empty_history()

    service = _service()
    frames = []

    for spreadsheet_id, group in selected.groupby(
        "_spreadsheet_id"
    ):
        records = group.sort_values(
            "snapshot_date"
        ).to_dict("records")

        frames.extend(
            _batch_get_records(
                service,
                spreadsheet_id,
                records,
            )
        )

    if not frames:
        return _empty_history()

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

    return (
        df.sort_values(
            [
                "snapshot_date",
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


def _empty_history() -> pd.DataFrame:
    return pd.DataFrame(
        columns=DATA_HEADERS
        + [
            "scope_key",
            "scope_name",
        ]
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
    start_date = (
        end_date
        - timedelta(days=days - 1)
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
        & (df["snapshot_date"] >= start_date)
        & (df["snapshot_date"] <= end_date)
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
