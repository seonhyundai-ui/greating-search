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

APP_VERSION = "0.4.0"

SHEET_NAME = "NAVER_FOOD_KEYWORD_RAW"
TIMEZONE = ZoneInfo("Asia/Seoul")

HEADERS = [
    "snapshot_date",
    "rank",
    "keyword",
    "category_id",
    "category_name",
    "collected_at",
]

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
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def _get_sheet_id(service, spreadsheet_id: str) -> int | None:
    spreadsheet = (
        service.spreadsheets()
        .get(
            spreadsheetId=spreadsheet_id,
            fields="sheets.properties(sheetId,title)",
        )
        .execute()
    )

    for sheet in spreadsheet.get("sheets", []):
        props = sheet.get("properties", {})
        if props.get("title") == SHEET_NAME:
            return props.get("sheetId")

    return None


def _ensure_sheet(service, spreadsheet_id: str) -> int:
    sheet_id = _get_sheet_id(service, spreadsheet_id)

    if sheet_id is None:
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

        sheet_id = response["replies"][0]["addSheet"]["properties"]["sheetId"]
        LOGGER.info("[SHEETS] created sheet: %s", SHEET_NAME)

    header_result = (
        service.spreadsheets()
        .values()
        .get(
            spreadsheetId=spreadsheet_id,
            range=f"'{SHEET_NAME}'!A1:F1",
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
                range=f"'{SHEET_NAME}'!A1:F1",
                valueInputOption="RAW",
                body={"values": [HEADERS]},
            )
            .execute()
        )
        LOGGER.info("[SHEETS] header created/updated")

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
                                "gridProperties": {"frozenRowCount": 1},
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
                                    "textFormat": {"bold": True}
                                }
                            },
                            "fields": "userEnteredFormat.textFormat.bold",
                        }
                    },
                ]
            },
        )
        .execute()
    )

    return sheet_id


def _read_snapshot_dates(service, spreadsheet_id: str) -> list[str]:
    try:
        result = (
            service.spreadsheets()
            .values()
            .get(
                spreadsheetId=spreadsheet_id,
                range=f"'{SHEET_NAME}'!A2:A",
            )
            .execute()
        )
    except Exception:
        # 파일은 있지만 RAW 탭이 아직 없는 신규 연도는 빈 상태로 취급
        return []

    values = result.get("values", [])
    dates: list[str] = []

    for row in values:
        if not row:
            continue

        value = str(row[0]).strip()

        try:
            _parse_date(value)
        except ValueError:
            continue

        dates.append(value)

    return dates


def _get_latest_snapshot_date(service):
    latest = None

    for year, spreadsheet_id in get_spreadsheet_ids().items():
        dates = _read_snapshot_dates(service, spreadsheet_id)

        if not dates:
            continue

        year_latest = max(_parse_date(value) for value in dates)

        if latest is None or year_latest > latest:
            latest = year_latest

    return latest


def _existing_snapshot_rows(
    service,
    spreadsheet_id: str,
    target_date: str,
) -> list[int]:
    result = (
        service.spreadsheets()
        .values()
        .get(
            spreadsheetId=spreadsheet_id,
            range=f"'{SHEET_NAME}'!A2:A",
        )
        .execute()
    )

    values = result.get("values", [])

    return [
        idx + 2
        for idx, row in enumerate(values)
        if row and str(row[0]).strip() == target_date
    ]


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


def _append_dataframe(service, spreadsheet_id: str, df) -> int:
    values = [
        [
            str(row.snapshot_date),
            int(row.rank),
            str(row.keyword),
            str(row.category_id),
            str(row.category_name),
            str(row.collected_at),
        ]
        for row in df.itertuples(index=False)
    ]

    response = (
        service.spreadsheets()
        .values()
        .append(
            spreadsheetId=spreadsheet_id,
            range=f"'{SHEET_NAME}'!A:F",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": values},
        )
        .execute()
    )

    return int(response.get("updates", {}).get("updatedRows", 0))


def _collect_and_upload_one(
    service,
    target_date: str,
    replace: bool = False,
) -> str:
    target = _parse_date(target_date)
    spreadsheet_id = get_spreadsheet_id(target.year)
    sheet_id = _ensure_sheet(service, spreadsheet_id)

    LOGGER.info(
        "[TARGET] %s -> NAVER_SEARCH_%s",
        target_date,
        target.year,
    )

    existing_rows = _existing_snapshot_rows(
        service,
        spreadsheet_id,
        target_date,
    )

    if existing_rows and not replace:
        LOGGER.info(
            "[SKIP] %s 데이터가 이미 %s행 존재합니다.",
            target_date,
            len(existing_rows),
        )
        return "SKIP"

    LOGGER.info("[NAVER] %s TOP 500 수집", target_date)
    df = fetch_food_keyword_rank(target_date=target_date)

    if len(df) != 500:
        raise RuntimeError(
            f"{target_date} NAVER 응답 행수 이상: expected=500, got={len(df)}"
        )

    if existing_rows and replace:
        LOGGER.info(
            "[REPLACE] %s existing rows=%s -> delete",
            target_date,
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
    )

    if updated_rows != len(df):
        raise RuntimeError(
            f"{target_date} Google Sheets 적재 행수 불일치: "
            f"expected={len(df)}, updated={updated_rows}"
        )

    LOGGER.info(
        "[SUCCESS] %s rows=%s | year=%s",
        target_date,
        updated_rows,
        target.year,
    )
    return "SUCCESS"


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
        start_date = latest_date + timedelta(days=1)
        LOGGER.info(
            "[AUTO] latest=%s | catch-up=%s ~ %s",
            latest_date.isoformat(),
            start_date.isoformat(),
            end_date.isoformat(),
        )

    if start_date > end_date:
        LOGGER.info(
            "[UP-TO-DATE] 최신 적재일=%s | D-1=%s | 추가 적재 없음",
            latest_date.isoformat() if latest_date else "-",
            end_date.isoformat(),
        )
        return

    targets = list(_date_range(start_date, end_date))

    LOGGER.info(
        "[CATCH-UP] %s일 적재 예정: %s",
        len(targets),
        ", ".join(d.isoformat() for d in targets),
    )

    success_count = 0

    for index, target in enumerate(targets, start=1):
        target_str = target.isoformat()

        LOGGER.info(
            "[%s/%s] %s 시작",
            index,
            len(targets),
            target_str,
        )

        try:
            result = _collect_and_upload_one(
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
                    "[CATCH-UP STOP] %s 이후 데이터는 다음 실행에서 다시 확인합니다.",
                    target_str,
                )
                return
            raise

        if result == "SUCCESS":
            success_count += 1

    LOGGER.info(
        "[CATCH-UP COMPLETE] requested=%s | success=%s",
        len(targets),
        success_count,
    )


def run_manual(target_date: str, replace: bool = False) -> None:
    _parse_date(target_date)
    service = _get_sheets_service()

    LOGGER.info(
        "[MANUAL] target=%s | replace=%s",
        target_date,
        replace,
    )

    _collect_and_upload_one(
        service=service,
        target_date=target_date,
        replace=replace,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "NAVER 식품 인기검색어 TOP 500 -> 연도별 Google Sheets 누적. "
            "날짜 생략 시 전체 연도 파일의 마지막 적재일 다음날부터 KST D-1까지 자동 보충."
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
        help="수동 날짜가 이미 있으면 삭제 후 재적재",
    )

    args = parser.parse_args()

    LOGGER.info("=" * 72)
    LOGGER.info("NAVER Food -> Yearly Google Sheets v%s", APP_VERSION)
    LOGGER.info("Configured years : %s", configured_years())
    LOGGER.info("Sheet            : %s", SHEET_NAME)
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
                    "--replace는 target_date를 직접 지정한 수동 실행에서만 사용할 수 있습니다."
                )
            run_catchup()

    except Exception:
        LOGGER.exception("[FAILED]")
        raise


if __name__ == "__main__":
    main()
