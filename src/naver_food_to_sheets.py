from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from googleapiclient.discovery import build

from src.google_sheets_auth import get_sheets_credentials
from src.naver_food_rank import fetch_food_keyword_rank
from src.naver_spreadsheet_config import (
    configured_years,
    get_spreadsheet_id,
    get_spreadsheet_ids,
)

APP_VERSION = "0.5.0"

SHEET_NAME = "NAVER_FOOD_KEYWORD_RAW"
TIMEZONE = ZoneInfo("Asia/Seoul")

# 기존 6개 컬럼은 그대로 유지하고 G/H만 추가한다.
# 따라서 기존 2025/2026 식품 전체 데이터 마이그레이션이 필요 없다.
HEADERS = [
    "snapshot_date",
    "rank",
    "keyword",
    "category_id",
    "category_name",
    "collected_at",
    "scope_key",
    "scope_name",
]

SCOPES = [
    {
        "scope_key": "FOOD_ALL",
        "scope_name": "식품 전체",
        "category_id": "50000006",
        "category_name": "식품",
    },
    {
        "scope_key": "FROZEN_CONVENIENCE",
        "scope_name": "냉동/간편조리식품",
        "category_id": "50000026",
        "category_name": "냉동/간편조리식품",
    },
    {
        "scope_key": "MEALKIT",
        "scope_name": "밀키트",
        "category_id": "50014240",
        "category_name": "밀키트",
    },
    {
        "scope_key": "INSTANT_RICE_SOUP",
        "scope_name": "즉석밥/즉석국",
        "category_id": "50020779",
        "category_name": "즉석밥/즉석국",
    },
]

SCOPE_KEYS = {scope["scope_key"] for scope in SCOPES}

LOG_DIR = Path("logs")
LOG_FILE = LOG_DIR / "naver_food_daily.log"


def setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("naver_food_to_sheets")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(
        LOG_FILE,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    return logger


LOGGER = setup_logging()


def _parse_date(value: str):
    return datetime.strptime(value, "%Y-%m-%d").date()


def _yesterday_kst():
    return datetime.now(TIMEZONE).date() - timedelta(days=1)


def _date_range(start_date, end_date):
    current = start_date

    while current <= end_date:
        yield current
        current += timedelta(days=1)


def _get_sheets_service():
    creds = get_sheets_credentials()
    return build(
        "sheets",
        "v4",
        credentials=creds,
        cache_discovery=False,
    )


def _get_sheet_properties(service, spreadsheet_id: str):
    spreadsheet = (
        service.spreadsheets()
        .get(
            spreadsheetId=spreadsheet_id,
            fields=(
                "sheets.properties("
                "sheetId,title,gridProperties(rowCount,columnCount)"
                ")"
            ),
        )
        .execute()
    )

    for sheet in spreadsheet.get("sheets", []):
        props = sheet.get("properties", {})

        if props.get("title") == SHEET_NAME:
            return props

    return None


def _ensure_sheet(service, spreadsheet_id: str) -> int:
    props = _get_sheet_properties(service, spreadsheet_id)

    if props is None:
        response = (
            service.spreadsheets()
            .batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={
                    "requests": [
                        {
                            "addSheet": {
                                "properties": {
                                    "title": SHEET_NAME,
                                    "gridProperties": {
                                        "rowCount": 1000,
                                        "columnCount": len(HEADERS),
                                        "frozenRowCount": 1,
                                    },
                                }
                            }
                        }
                    ]
                },
            )
            .execute()
        )

        props = response["replies"][0]["addSheet"]["properties"]
        LOGGER.info("[SHEETS] created sheet: %s", SHEET_NAME)

    sheet_id = props["sheetId"]
    column_count = int(
        props.get("gridProperties", {}).get("columnCount", 0)
    )

    if column_count < len(HEADERS):
        (
            service.spreadsheets()
            .batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={
                    "requests": [
                        {
                            "appendDimension": {
                                "sheetId": sheet_id,
                                "dimension": "COLUMNS",
                                "length": len(HEADERS) - column_count,
                            }
                        }
                    ]
                },
            )
            .execute()
        )
        LOGGER.info(
            "[SHEETS] columns expanded: %s -> %s",
            column_count,
            len(HEADERS),
        )

    header_result = (
        service.spreadsheets()
        .values()
        .get(
            spreadsheetId=spreadsheet_id,
            range=f"'{SHEET_NAME}'!A1:H1",
        )
        .execute()
    )

    current = header_result.get("values", [])

    if not current or current[0] != HEADERS:
        (
            service.spreadsheets()
            .values()
            .update(
                spreadsheetId=spreadsheet_id,
                range=f"'{SHEET_NAME}'!A1:H1",
                valueInputOption="RAW",
                body={"values": [HEADERS]},
            )
            .execute()
        )
        LOGGER.info("[SHEETS] header created/updated to 8 columns")

    (
        service.spreadsheets()
        .batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={
                "requests": [
                    {
                        "updateSheetProperties": {
                            "properties": {
                                "sheetId": sheet_id,
                                "gridProperties": {
                                    "frozenRowCount": 1
                                },
                            },
                            "fields": "gridProperties.frozenRowCount",
                        }
                    },
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": sheet_id,
                                "startRowIndex": 0,
                                "endRowIndex": 1,
                                "startColumnIndex": 0,
                                "endColumnIndex": len(HEADERS),
                            },
                            "cell": {
                                "userEnteredFormat": {
                                    "textFormat": {
                                        "bold": True
                                    }
                                }
                            },
                            "fields": (
                                "userEnteredFormat."
                                "textFormat.bold"
                            ),
                        }
                    },
                ]
            },
        )
        .execute()
    )

    return sheet_id


def _read_snapshot_scope_rows(
    service,
    spreadsheet_id: str,
):
    try:
        result = (
            service.spreadsheets()
            .values()
            .get(
                spreadsheetId=spreadsheet_id,
                range=f"'{SHEET_NAME}'!A2:H",
            )
            .execute()
        )
    except Exception:
        return []

    values = result.get("values", [])
    parsed = []

    for idx, row in enumerate(values, start=2):
        padded = list(row) + [""] * (8 - len(row))
        snapshot_date = str(padded[0]).strip()

        try:
            _parse_date(snapshot_date)
        except ValueError:
            continue

        category_id = str(padded[3]).strip()
        scope_key = str(padded[6]).strip()

        # 기존 6컬럼 데이터는 모두 '식품 전체'로 간주.
        if not scope_key:
            if category_id == "50000006":
                scope_key = "FOOD_ALL"
            else:
                scope_key = f"LEGACY_{category_id or 'UNKNOWN'}"

        parsed.append(
            {
                "row_number": idx,
                "snapshot_date": snapshot_date,
                "scope_key": scope_key,
            }
        )

    return parsed


def _get_latest_snapshot_date(service):
    latest = None

    for year, spreadsheet_id in get_spreadsheet_ids().items():
        rows = _read_snapshot_scope_rows(
            service,
            spreadsheet_id,
        )

        if not rows:
            continue

        year_latest = max(
            _parse_date(row["snapshot_date"])
            for row in rows
        )

        if latest is None or year_latest > latest:
            latest = year_latest

    return latest


def _existing_scope_rows(
    service,
    spreadsheet_id: str,
    target_date: str,
    scope_key: str,
) -> list[int]:
    rows = _read_snapshot_scope_rows(
        service,
        spreadsheet_id,
    )

    return [
        row["row_number"]
        for row in rows
        if (
            row["snapshot_date"] == target_date
            and row["scope_key"] == scope_key
        )
    ]


def _scope_keys_for_date(
    service,
    spreadsheet_id: str,
    target_date: str,
) -> set[str]:
    rows = _read_snapshot_scope_rows(
        service,
        spreadsheet_id,
    )

    return {
        row["scope_key"]
        for row in rows
        if row["snapshot_date"] == target_date
    }


def _delete_rows(
    service,
    spreadsheet_id: str,
    sheet_id: int,
    row_numbers: list[int],
) -> None:
    if not row_numbers:
        return

    blocks: list[tuple[int, int]] = []
    start = prev = row_numbers[0]

    for row_num in row_numbers[1:]:
        if row_num == prev + 1:
            prev = row_num
            continue

        blocks.append((start, prev))
        start = prev = row_num

    blocks.append((start, prev))

    requests = []

    for start_row, end_row in reversed(blocks):
        requests.append(
            {
                "deleteDimension": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "ROWS",
                        "startIndex": start_row - 1,
                        "endIndex": end_row,
                    }
                }
            }
        )

    (
        service.spreadsheets()
        .batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": requests},
        )
        .execute()
    )


def _append_dataframe(
    service,
    spreadsheet_id: str,
    df,
    scope_key: str,
    scope_name: str,
) -> int:
    values = [
        [
            str(row.snapshot_date),
            int(row.rank),
            str(row.keyword),
            str(row.category_id),
            str(row.category_name),
            str(row.collected_at),
            scope_key,
            scope_name,
        ]
        for row in df.itertuples(index=False)
    ]

    response = (
        service.spreadsheets()
        .values()
        .append(
            spreadsheetId=spreadsheet_id,
            range=f"'{SHEET_NAME}'!A:H",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": values},
        )
        .execute()
    )

    return int(
        response.get(
            "updates",
            {},
        ).get(
            "updatedRows",
            0,
        )
    )


def _collect_and_upload_scope(
    service,
    spreadsheet_id: str,
    sheet_id: int,
    target_date: str,
    scope: dict,
    replace: bool = False,
) -> str:
    scope_key = scope["scope_key"]
    scope_name = scope["scope_name"]

    existing_rows = _existing_scope_rows(
        service,
        spreadsheet_id,
        target_date,
        scope_key,
    )

    if existing_rows and not replace:
        LOGGER.info(
            "[SKIP] %s | %s already exists rows=%s",
            target_date,
            scope_name,
            len(existing_rows),
        )
        return "SKIP"

    LOGGER.info(
        "[NAVER] %s | %s TOP 500 수집",
        target_date,
        scope_name,
    )

    df = fetch_food_keyword_rank(
        target_date=target_date,
        category_id=scope["category_id"],
        category_name=scope["category_name"],
    )

    if len(df) != 500:
        raise RuntimeError(
            f"{target_date} / {scope_name} NAVER 응답 행수 이상: "
            f"expected=500, got={len(df)}"
        )

    if existing_rows and replace:
        LOGGER.info(
            "[REPLACE] %s | %s rows=%s -> delete",
            target_date,
            scope_name,
            len(existing_rows),
        )

        _delete_rows(
            service,
            spreadsheet_id,
            sheet_id,
            existing_rows,
        )

    updated_rows = _append_dataframe(
        service,
        spreadsheet_id,
        df,
        scope_key,
        scope_name,
    )

    if updated_rows != len(df):
        raise RuntimeError(
            f"{target_date} / {scope_name} Google Sheets 적재 행수 불일치: "
            f"expected={len(df)}, updated={updated_rows}"
        )

    LOGGER.info(
        "[SUCCESS] %s | %s rows=%s",
        target_date,
        scope_name,
        updated_rows,
    )
    return "SUCCESS"


def _collect_and_upload_date(
    service,
    target_date: str,
    replace: bool = False,
) -> dict[str, int]:
    target = _parse_date(target_date)
    spreadsheet_id = get_spreadsheet_id(target.year)
    sheet_id = _ensure_sheet(
        service,
        spreadsheet_id,
    )

    LOGGER.info(
        "[TARGET] %s -> NAVER_SEARCH_%s",
        target_date,
        target.year,
    )

    stats = {
        "SUCCESS": 0,
        "SKIP": 0,
    }

    for index, scope in enumerate(SCOPES, start=1):
        LOGGER.info(
            "[SCOPE %s/%s] %s",
            index,
            len(SCOPES),
            scope["scope_name"],
        )

        result = _collect_and_upload_scope(
            service=service,
            spreadsheet_id=spreadsheet_id,
            sheet_id=sheet_id,
            target_date=target_date,
            scope=scope,
            replace=replace,
        )

        stats[result] += 1

    return stats


def _latest_date_needs_scope_backfill(
    service,
    latest_date,
) -> bool:
    if latest_date is None:
        return False

    spreadsheet_id = get_spreadsheet_id(
        latest_date.year
    )

    existing = _scope_keys_for_date(
        service,
        spreadsheet_id,
        latest_date.isoformat(),
    )

    return not SCOPE_KEYS.issubset(existing)


def run_catchup() -> None:
    service = _get_sheets_service()

    latest_date = _get_latest_snapshot_date(service)
    end_date = _yesterday_kst()

    if latest_date is None:
        start_date = end_date
        LOGGER.info(
            "[AUTO] 저장된 날짜 없음 -> D-1(%s) 1일만 최초 적재",
            end_date.isoformat(),
        )
    else:
        # 기존 최신 날짜가 FOOD_ALL만 있는 경우,
        # 그 날짜부터 다시 시작해 누락된 3개 세부 분류를 채운다.
        if _latest_date_needs_scope_backfill(
            service,
            latest_date,
        ):
            start_date = latest_date
            LOGGER.info(
                "[AUTO] latest=%s has missing scopes -> "
                "same date부터 세부분류 보충",
                latest_date.isoformat(),
            )
        else:
            start_date = latest_date + timedelta(days=1)
            LOGGER.info(
                "[AUTO] latest=%s complete | catch-up=%s ~ %s",
                latest_date.isoformat(),
                start_date.isoformat(),
                end_date.isoformat(),
            )

    if start_date > end_date:
        LOGGER.info(
            "[UP-TO-DATE] latest=%s | D-1=%s | 추가 적재 없음",
            latest_date.isoformat() if latest_date else "-",
            end_date.isoformat(),
        )
        return

    targets = list(
        _date_range(
            start_date,
            end_date,
        )
    )

    LOGGER.info(
        "[CATCH-UP] %s일 적재 예정: %s",
        len(targets),
        ", ".join(
            date.isoformat()
            for date in targets
        ),
    )

    completed_dates = 0

    for index, target in enumerate(targets, start=1):
        target_str = target.isoformat()

        LOGGER.info(
            "[DATE %s/%s] %s 시작",
            index,
            len(targets),
            target_str,
        )

        try:
            stats = _collect_and_upload_date(
                service=service,
                target_date=target_str,
                replace=False,
            )
        except RuntimeError as exc:
            if "No ranking data returned for" in str(exc):
                LOGGER.warning(
                    "[WAIT] 네이버 데이터랩이 아직 업데이트되지 않았습니다. "
                    "target_date=%s",
                    target_str,
                )
                LOGGER.info(
                    "[CATCH-UP STOP] %s 이후 데이터는 "
                    "다음 실행에서 다시 확인합니다.",
                    target_str,
                )
                return
            raise

        LOGGER.info(
            "[DATE COMPLETE] %s | success_scopes=%s | skip_scopes=%s",
            target_str,
            stats["SUCCESS"],
            stats["SKIP"],
        )
        completed_dates += 1

    LOGGER.info(
        "[CATCH-UP COMPLETE] dates=%s",
        completed_dates,
    )


def run_manual(
    target_date: str,
    replace: bool = False,
) -> None:
    _parse_date(target_date)
    service = _get_sheets_service()

    LOGGER.info(
        "[MANUAL] target=%s | replace=%s",
        target_date,
        replace,
    )

    _collect_and_upload_date(
        service=service,
        target_date=target_date,
        replace=replace,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "NAVER 식품 전체 + 3개 세부분류 TOP500 -> 연도별 Google Sheets 누적. "
            "날짜 생략 시 최신 날짜의 누락 분류를 보충한 뒤 D-1까지 자동 적재."
        )
    )

    parser.add_argument(
        "target_date",
        nargs="?",
        default=None,
        help="수동 적재 날짜 YYYY-MM-DD. 생략하면 자동 catch-up",
    )

    parser.add_argument(
        "--replace",
        action="store_true",
        help="수동 날짜의 4개 분류를 모두 삭제 후 재적재",
    )

    args = parser.parse_args()

    LOGGER.info("=" * 72)
    LOGGER.info(
        "NAVER Food Scope Pipeline v%s",
        APP_VERSION,
    )
    LOGGER.info(
        "Configured years : %s",
        configured_years(),
    )
    LOGGER.info(
        "Scopes           : %s",
        [scope["scope_name"] for scope in SCOPES],
    )
    LOGGER.info(
        "Sheet            : %s",
        SHEET_NAME,
    )
    LOGGER.info("=" * 72)

    try:
        if args.target_date:
            run_manual(
                target_date=args.target_date,
                replace=args.replace,
            )
        else:
            if args.replace:
                raise ValueError(
                    "--replace는 target_date를 지정한 수동 실행에서만 사용할 수 있습니다."
                )

            run_catchup()

    except Exception:
        LOGGER.exception("[FAILED]")
        raise


if __name__ == "__main__":
    main()
