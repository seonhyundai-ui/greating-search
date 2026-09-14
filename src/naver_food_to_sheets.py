from __future__ import annotations

import argparse
import logging
import random
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from src.google_sheets_auth import get_sheets_credentials
from src.naver_food_rank import fetch_food_keyword_rank
from src.naver_monthly_store import (
    DATA_HEADERS,
    META_HEADERS,
    META_SHEET,
    SCOPES,
    SCOPE_ORDER,
    monthly_sheet_name,
)
from src.naver_spreadsheet_config import (
    configured_years,
    get_spreadsheet_id,
    get_spreadsheet_ids,
)

APP_VERSION = "0.7.0"
TIMEZONE = ZoneInfo("Asia/Seoul")

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


def _service():
    return build(
        "sheets",
        "v4",
        credentials=get_sheets_credentials(),
        cache_discovery=False,
    )


def _execute_with_retry(
    request,
    *,
    label: str,
    max_attempts: int = 6,
):
    """
    일시적 429/5xx 오류 재시도.
    같은 range에 values.update 하는 DATA 쓰기에 사용한다.
    """
    retry_statuses = {429, 500, 502, 503, 504}

    for attempt in range(1, max_attempts + 1):
        try:
            return request.execute()
        except HttpError as exc:
            status = getattr(exc.resp, "status", None)

            if status not in retry_statuses or attempt >= max_attempts:
                raise

            wait_seconds = min(
                30.0,
                (2 ** (attempt - 1)) + random.uniform(0.2, 1.0),
            )

            LOGGER.warning(
                "[RETRY] %s | HTTP %s | %s/%s | %.1f초 후 재시도",
                label,
                status,
                attempt,
                max_attempts,
                wait_seconds,
            )
            time.sleep(wait_seconds)


def _sheet_properties(
    service,
    spreadsheet_id: str,
) -> dict[str, dict]:
    result = (
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

    return {
        sheet["properties"]["title"]: sheet["properties"]
        for sheet in result.get("sheets", [])
    }


def _ensure_sheet(
    service,
    spreadsheet_id: str,
    title: str,
    columns: int,
) -> int:
    props = _sheet_properties(
        service,
        spreadsheet_id,
    ).get(title)

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
                                    "title": title,
                                    "gridProperties": {
                                        "rowCount": 1000,
                                        "columnCount": columns,
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

        sheet_id = int(
            response["replies"][0]["addSheet"]["properties"]["sheetId"]
        )

        (
            service.spreadsheets()
            .values()
            .update(
                spreadsheetId=spreadsheet_id,
                range=f"'{title}'!A1",
                valueInputOption="RAW",
                body={
                    "values": [
                        META_HEADERS
                        if title == META_SHEET
                        else DATA_HEADERS
                    ]
                },
            )
            .execute()
        )

        LOGGER.info("[SHEETS] created: %s", title)
        return sheet_id

    return int(props["sheetId"])


def _ensure_row_capacity(
    service,
    spreadsheet_id: str,
    title: str,
    required_rows: int,
) -> None:
    """
    values.update() 전에 필요한 grid row 수를 확보한다.
    월별 TOP500 누적 탭은 한 달 최대 약 15,500행이므로 필수다.
    """
    props = _sheet_properties(
        service,
        spreadsheet_id,
    ).get(title)

    if props is None:
        raise RuntimeError(
            f"시트가 없습니다: {title}"
        )

    sheet_id = int(props["sheetId"])
    current_rows = int(
        props.get("gridProperties", {}).get("rowCount", 0)
    )

    if current_rows >= required_rows:
        return

    (
        service.spreadsheets()
        .batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={
                "requests": [
                    {
                        "appendDimension": {
                            "sheetId": sheet_id,
                            "dimension": "ROWS",
                            "length": required_rows - current_rows,
                        }
                    }
                ]
            },
        )
        .execute()
    )


def _read_meta(
    service,
    spreadsheet_id: str,
) -> list[dict]:
    props = _sheet_properties(
        service,
        spreadsheet_id,
    )

    if META_SHEET not in props:
        return []

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

    result = []

    for row_number, raw in enumerate(values, start=2):
        row = list(raw) + [""] * (10 - len(raw))

        if not str(row[0]).strip():
            continue

        result.append(
            {
                "_row_number": row_number,
                "snapshot_date": str(row[0]).strip(),
                "scope_key": str(row[1]).strip(),
                "scope_name": str(row[2]).strip(),
                "sheet_name": str(row[3]).strip(),
                "row_start": str(row[4]).strip(),
                "row_end": str(row[5]).strip(),
                "row_count": str(row[6]).strip(),
                "status": str(row[7]).strip(),
                "category_id": str(row[8]).strip(),
                "updated_at": str(row[9]).strip(),
            }
        )

    return result


def _find_meta(
    meta_rows: list[dict],
    target_date: str,
    scope_key: str,
) -> dict | None:
    for row in meta_rows:
        if (
            row["snapshot_date"] == target_date
            and row["scope_key"] == scope_key
        ):
            return row
    return None


def _meta_row_values(record: dict) -> list:
    return [
        record["snapshot_date"],
        record["scope_key"],
        record["scope_name"],
        record["sheet_name"],
        record["row_start"],
        record["row_end"],
        record["row_count"],
        record["status"],
        record["category_id"],
        record["updated_at"],
    ]


def _upsert_meta(
    service,
    spreadsheet_id: str,
    meta_rows: list[dict],
    record: dict,
) -> None:
    _ensure_sheet(
        service,
        spreadsheet_id,
        META_SHEET,
        columns=len(META_HEADERS),
    )

    existing = _find_meta(
        meta_rows,
        record["snapshot_date"],
        record["scope_key"],
    )

    if existing:
        row_number = existing["_row_number"]

        _ensure_row_capacity(
            service,
            spreadsheet_id,
            META_SHEET,
            required_rows=max(2, int(row_number)),
        )

        (
            service.spreadsheets()
            .values()
            .update(
                spreadsheetId=spreadsheet_id,
                range=f"'{META_SHEET}'!A{row_number}:J{row_number}",
                valueInputOption="RAW",
                body={"values": [_meta_row_values(record)]},
            )
            .execute()
        )

        existing.update(record)
        return

    # append 직전 현재 META 행 수 + 1행을 확보한다.
    meta_props = _sheet_properties(
        service,
        spreadsheet_id,
    )[META_SHEET]
    current_meta_rows = int(
        meta_props.get("gridProperties", {}).get("rowCount", 0)
    )
    next_meta_row = max(
        2,
        len(meta_rows) + 2,
    )

    if current_meta_rows < next_meta_row:
        _ensure_row_capacity(
            service,
            spreadsheet_id,
            META_SHEET,
            required_rows=next_meta_row,
        )

    response = (
        service.spreadsheets()
        .values()
        .append(
            spreadsheetId=spreadsheet_id,
            range=f"'{META_SHEET}'!A:J",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [_meta_row_values(record)]},
        )
        .execute()
    )

    updated_range = (
        response.get("updates", {})
        .get("updatedRange", "")
    )

    # updatedRange 예: NAVER_META!A15:J15
    row_number = None
    if "!" in updated_range:
        tail = updated_range.split("!", 1)[1]
        digits = "".join(
            char
            for char in tail.split(":")[0]
            if char.isdigit()
        )
        if digits:
            row_number = int(digits)

    meta_rows.append(
        {
            **record,
            "_row_number": row_number or 0,
        }
    )


def _next_data_row(
    service,
    spreadsheet_id: str,
    sheet_name: str,
) -> int:
    values = (
        service.spreadsheets()
        .values()
        .get(
            spreadsheetId=spreadsheet_id,
            range=f"'{sheet_name}'!A:A",
        )
        .execute()
        .get("values", [])
    )

    return max(2, len(values) + 1)


def _clear_old_range_if_needed(
    service,
    spreadsheet_id: str,
    existing_meta: dict | None,
) -> None:
    if not existing_meta:
        return

    if existing_meta.get("status") != "DATA":
        return

    sheet_name = existing_meta.get("sheet_name", "")
    row_start = existing_meta.get("row_start", "")
    row_end = existing_meta.get("row_end", "")

    if not (
        sheet_name
        and str(row_start).isdigit()
        and str(row_end).isdigit()
    ):
        return

    (
        service.spreadsheets()
        .values()
        .clear(
            spreadsheetId=spreadsheet_id,
            range=(
                f"'{sheet_name}'!"
                f"A{row_start}:F{row_end}"
            ),
            body={},
        )
        .execute()
    )


def _append_data(
    service,
    spreadsheet_id: str,
    sheet_name: str,
    df,
) -> tuple[int, int]:
    _ensure_sheet(
        service,
        spreadsheet_id,
        sheet_name,
        columns=len(DATA_HEADERS),
    )

    start_row = _next_data_row(
        service,
        spreadsheet_id,
        sheet_name,
    )

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

    end_row = start_row + len(values) - 1

    _ensure_row_capacity(
        service,
        spreadsheet_id,
        sheet_name,
        required_rows=end_row,
    )

    request = (
        service.spreadsheets()
        .values()
        .update(
            spreadsheetId=spreadsheet_id,
            range=f"'{sheet_name}'!A{start_row}:F{end_row}",
            valueInputOption="RAW",
            body={"values": values},
        )
    )

    _execute_with_retry(
        request,
        label=f"{sheet_name} A{start_row}:F{end_row}",
    )

    return start_row, end_row


def _collect_scope(
    service,
    spreadsheet_id: str,
    meta_rows: list[dict],
    target_date: str,
    scope: dict,
    replace: bool,
) -> str:
    scope_key = scope["scope_key"]
    scope_name = scope["scope_name"]

    existing = _find_meta(
        meta_rows,
        target_date,
        scope_key,
    )

    if existing and not replace:
        LOGGER.info(
            "[SKIP] %s | %s | status=%s",
            target_date,
            scope_name,
            existing["status"],
        )
        return "SKIP"

    try:
        df = fetch_food_keyword_rank(
            target_date=target_date,
            category_id=scope["category_id"],
            category_name=scope["category_name"],
        )
    except RuntimeError as exc:
        if "No ranking data returned for" not in str(exc):
            raise

        target = _parse_date(target_date)

        # D-1 데이터는 NAVER가 아직 게시하지 않았을 수 있다.
        # 이때 NO_DATA marker를 남기면 이후 자동 수집이 영원히 SKIP될 수 있으므로
        # META에 기록하지 않고 WAIT로 종료한다.
        if target >= _yesterday_kst():
            LOGGER.warning(
                "[WAIT] %s | %s | NAVER 데이터가 아직 게시되지 않음",
                target_date,
                scope_name,
            )
            return "WAIT"

        # 과거 날짜는 실제로 해당 분류 데이터가 없을 수 있으므로
        # NO_DATA marker를 기록하여 반복 조회를 방지한다.
        if replace:
            _clear_old_range_if_needed(
                service,
                spreadsheet_id,
                existing,
            )

        record = {
            "snapshot_date": target_date,
            "scope_key": scope_key,
            "scope_name": scope_name,
            "sheet_name": monthly_sheet_name(
                scope_key,
                target,
            ),
            "row_start": "",
            "row_end": "",
            "row_count": 0,
            "status": "NO_DATA",
            "category_id": scope["category_id"],
            "updated_at": datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
        }

        _upsert_meta(
            service,
            spreadsheet_id,
            meta_rows,
            record,
        )

        LOGGER.warning(
            "[NO DATA] %s | %s -> META only",
            target_date,
            scope_name,
        )
        return "NO_DATA"

    row_count = len(df)

    # NAVER DataLab의 과거 카테고리는 특정 날짜에
    # 실제 제공 랭킹이 500개 미만일 수 있다.
    # 1~500행은 정상 데이터로 저장하고, 500행 미만은 경고만 남긴다.
    if row_count <= 0:
        raise RuntimeError(
            f"{target_date} / {scope_name} "
            "ranking data is empty"
        )

    if row_count > 500:
        raise RuntimeError(
            f"{target_date} / {scope_name} "
            f"unexpected ranking rows: {row_count} (>500)"
        )

    if row_count < 500:
        LOGGER.warning(
            "[PARTIAL DATA] %s | %s | rows=%s/500 "
            "| NAVER 제공 랭킹 수만 저장",
            target_date,
            scope_name,
            row_count,
        )

    if replace:
        _clear_old_range_if_needed(
            service,
            spreadsheet_id,
            existing,
        )

    target = _parse_date(target_date)
    sheet_name = monthly_sheet_name(
        scope_key,
        target,
    )

    start_row, end_row = _append_data(
        service,
        spreadsheet_id,
        sheet_name,
        df,
    )

    record = {
        "snapshot_date": target_date,
        "scope_key": scope_key,
        "scope_name": scope_name,
        "sheet_name": sheet_name,
        "row_start": start_row,
        "row_end": end_row,
        "row_count": len(df),
        "status": "DATA",
        "category_id": scope["category_id"],
        "updated_at": datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
    }

    _upsert_meta(
        service,
        spreadsheet_id,
        meta_rows,
        record,
    )

    LOGGER.info(
        "[SUCCESS] %s | %s | %s!%s:%s",
        target_date,
        scope_name,
        sheet_name,
        start_row,
        end_row,
    )

    return "SUCCESS"


def _collect_date(
    service,
    target_date: str,
    replace: bool = False,
) -> dict[str, int]:
    target = _parse_date(target_date)
    spreadsheet_id = get_spreadsheet_id(target.year)

    _ensure_sheet(
        service,
        spreadsheet_id,
        META_SHEET,
        columns=len(META_HEADERS),
    )

    meta_rows = _read_meta(
        service,
        spreadsheet_id,
    )

    stats = {
        "SUCCESS": 0,
        "SKIP": 0,
        "NO_DATA": 0,
        "WAIT": 0,
    }

    LOGGER.info(
        "[TARGET] %s -> NAVER_SEARCH_%s",
        target_date,
        target.year,
    )

    for index, scope in enumerate(SCOPES, start=1):
        LOGGER.info(
            "[SCOPE %s/%s] %s",
            index,
            len(SCOPES),
            scope["scope_name"],
        )

        result = _collect_scope(
            service=service,
            spreadsheet_id=spreadsheet_id,
            meta_rows=meta_rows,
            target_date=target_date,
            scope=scope,
            replace=replace,
        )

        stats[result] += 1

    return stats


def _all_meta_rows(service) -> list[dict]:
    rows = []

    for year, spreadsheet_id in get_spreadsheet_ids().items():
        try:
            year_rows = _read_meta(
                service,
                spreadsheet_id,
            )
        except Exception:
            continue

        for row in year_rows:
            row["_year"] = year
            rows.append(row)

    return rows


def _latest_complete_date(
    service,
):
    meta_rows = _all_meta_rows(service)

    if not meta_rows:
        return None

    by_date: dict[str, set[str]] = {}

    for row in meta_rows:
        by_date.setdefault(
            row["snapshot_date"],
            set(),
        ).add(row["scope_key"])

    required = set(SCOPE_ORDER)
    complete_dates = [
        _parse_date(date_str)
        for date_str, scopes in by_date.items()
        if required.issubset(scopes)
    ]

    if complete_dates:
        return max(complete_dates)

    # 아직 완전한 날짜가 하나도 없으면 가장 최신 존재 날짜부터 보충.
    return max(
        _parse_date(row["snapshot_date"])
        for row in meta_rows
    ) - timedelta(days=1)


def run_catchup() -> dict:
    service = _service()
    latest_complete = _latest_complete_date(service)
    end_date = _yesterday_kst()

    if latest_complete is None:
        start_date = end_date
    else:
        start_date = latest_complete + timedelta(days=1)

    if start_date > end_date:
        LOGGER.info(
            "[UP-TO-DATE] latest_complete=%s | D-1=%s",
            latest_complete,
            end_date,
        )
        return {
            "status": "UP_TO_DATE",
            "latest_complete": (
                latest_complete.isoformat()
                if latest_complete
                else None
            ),
            "target_date": end_date.isoformat(),
        }

    targets = list(
        _date_range(
            start_date,
            end_date,
        )
    )

    LOGGER.info(
        "[CATCH-UP] %s ~ %s | %s일",
        start_date,
        end_date,
        len(targets),
    )

    for index, target in enumerate(targets, start=1):
        target_str = target.isoformat()

        LOGGER.info(
            "[DATE %s/%s] %s",
            index,
            len(targets),
            target_str,
        )

        stats = _collect_date(
            service,
            target_str,
            replace=False,
        )

        LOGGER.info(
            "[DATE COMPLETE] %s | success=%s skip=%s no_data=%s wait=%s",
            target_str,
            stats["SUCCESS"],
            stats["SKIP"],
            stats["NO_DATA"],
            stats["WAIT"],
        )

        if stats["WAIT"] > 0:
            LOGGER.warning(
                "[CATCH-UP WAIT] %s | NAVER 최신 데이터 게시 대기",
                target_str,
            )
            return {
                "status": "WAIT",
                "target_date": target_str,
                **stats,
            }

    return {
        "status": "SUCCESS",
        "target_date": end_date.isoformat(),
    }


def run_manual(
    target_date: str,
    replace: bool = False,
) -> dict:
    _parse_date(target_date)

    stats = _collect_date(
        _service(),
        target_date,
        replace=replace,
    )

    LOGGER.info(
        "[MANUAL COMPLETE] %s | success=%s skip=%s no_data=%s wait=%s",
        target_date,
        stats["SUCCESS"],
        stats["SKIP"],
        stats["NO_DATA"],
        stats["WAIT"],
    )

    status = "WAIT" if stats["WAIT"] > 0 else "SUCCESS"

    return {
        "status": status,
        "target_date": target_date,
        **stats,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "NAVER 식품 4개 분류 TOP500 -> "
            "연도별 Spreadsheet / 월×분류 탭 적재"
        )
    )

    parser.add_argument(
        "target_date",
        nargs="?",
        default=None,
        help="YYYY-MM-DD. 생략하면 META 기준 D-1까지 catch-up",
    )

    parser.add_argument(
        "--replace",
        action="store_true",
        help="지정 날짜의 기존 범위를 clear 후 재적재",
    )

    args = parser.parse_args()

    LOGGER.info("=" * 78)
    LOGGER.info(
        "NAVER Monthly Scope Pipeline v%s",
        APP_VERSION,
    )
    LOGGER.info(
        "Configured years : %s",
        configured_years(),
    )
    LOGGER.info(
        "Storage          : yearly spreadsheet / monthly scope tabs",
    )
    LOGGER.info("=" * 78)

    try:
        if args.target_date:
            run_manual(
                args.target_date,
                replace=args.replace,
            )
        else:
            if args.replace:
                raise ValueError(
                    "--replace는 날짜를 지정한 경우에만 사용할 수 있습니다."
                )
            result = run_catchup()

            if result.get("status") == "WAIT":
                raise RuntimeError(
                    f"NAVER 최신 데이터가 아직 게시되지 않았습니다: "
                    f"{result.get('target_date')}"
                )
    except Exception:
        LOGGER.exception("[FAILED]")
        raise


if __name__ == "__main__":
    main()
