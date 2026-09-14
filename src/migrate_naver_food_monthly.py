from __future__ import annotations

import argparse
import random
import time
from collections import defaultdict
from datetime import datetime
from typing import Iterable

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from src.google_sheets_auth import get_sheets_credentials
from src.naver_monthly_store import (
    DATA_HEADERS,
    LEGACY_RAW_SHEET,
    META_HEADERS,
    META_SHEET,
    SCOPES,
    SCOPE_BY_KEY,
    SCOPE_ORDER,
    monthly_sheet_name,
    scope_for_legacy_row,
)
from src.naver_spreadsheet_config import get_spreadsheet_id

APP_VERSION = "0.1.2"
READ_CHUNK_ROWS = 10000
WRITE_CHUNK_ROWS = 5000


def _parse_date(value: str):
    return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()


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
    Google Sheets의 일시적 429/5xx 오류만 재시도한다.
    values.update처럼 같은 range에 다시 쓰는 요청은 재시도해도 안전하다.
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

            print(
                f"[RETRY] {label} | HTTP {status} | "
                f"{attempt}/{max_attempts} | "
                f"{wait_seconds:.1f}초 후 재시도"
            )
            time.sleep(wait_seconds)


def _sheet_properties(service, spreadsheet_id: str) -> dict[str, dict]:
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
    props = _sheet_properties(service, spreadsheet_id).get(title)

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
        return response["replies"][0]["addSheet"]["properties"]["sheetId"]

    sheet_id = int(props["sheetId"])
    current_columns = int(
        props.get("gridProperties", {}).get("columnCount", 0)
    )

    if current_columns < columns:
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
                                "length": columns - current_columns,
                            }
                        }
                    ]
                },
            )
            .execute()
        )

    return sheet_id


def _last_raw_row(
    service,
    spreadsheet_id: str,
) -> int:
    values = (
        service.spreadsheets()
        .values()
        .get(
            spreadsheetId=spreadsheet_id,
            range=f"'{LEGACY_RAW_SHEET}'!A:A",
        )
        .execute()
        .get("values", [])
    )
    return len(values)


def _read_raw_rows(
    service,
    spreadsheet_id: str,
) -> Iterable[list[str]]:
    last_row = _last_raw_row(service, spreadsheet_id)

    if last_row <= 1:
        return

    for start in range(2, last_row + 1, READ_CHUNK_ROWS):
        end = min(start + READ_CHUNK_ROWS - 1, last_row)

        values = (
            service.spreadsheets()
            .values()
            .get(
                spreadsheetId=spreadsheet_id,
                range=f"'{LEGACY_RAW_SHEET}'!A{start}:H{end}",
            )
            .execute()
            .get("values", [])
        )

        for row in values:
            yield list(row) + [""] * (8 - len(row))


def _ensure_row_capacity(
    service,
    spreadsheet_id: str,
    title: str,
    required_rows: int,
) -> None:
    """
    values.update()는 시트의 현재 grid row 수를 자동으로 늘리지 않는다.
    쓰기 전에 필요한 행 수까지 grid를 확장한다.
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

    add_rows = required_rows - current_rows

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
                            "length": add_rows,
                        }
                    }
                ]
            },
        )
        .execute()
    )


def _clear_sheet_values(
    service,
    spreadsheet_id: str,
    title: str,
) -> None:
    (
        service.spreadsheets()
        .values()
        .clear(
            spreadsheetId=spreadsheet_id,
            range=f"'{title}'!A:Z",
            body={},
        )
        .execute()
    )


def _write_values(
    service,
    spreadsheet_id: str,
    title: str,
    rows: list[list],
    columns_end: str,
) -> None:
    if not rows:
        return

    # Header 포함 전체 row 수만큼 먼저 grid를 확장한다.
    _ensure_row_capacity(
        service,
        spreadsheet_id,
        title,
        required_rows=len(rows),
    )

    for offset in range(0, len(rows), WRITE_CHUNK_ROWS):
        chunk = rows[offset:offset + WRITE_CHUNK_ROWS]
        start_row = offset + 1
        end_row = start_row + len(chunk) - 1

        request = (
            service.spreadsheets()
            .values()
            .update(
                spreadsheetId=spreadsheet_id,
                range=(
                    f"'{title}'!A{start_row}:"
                    f"{columns_end}{end_row}"
                ),
                valueInputOption="RAW",
                body={"values": chunk},
            )
        )

        _execute_with_retry(
            request,
            label=(
                f"{title} "
                f"A{start_row}:{columns_end}{end_row}"
            ),
        )


def migrate_year(
    year: int,
    dry_run: bool = False,
) -> None:
    spreadsheet_id = get_spreadsheet_id(year)
    service = _service()

    props = _sheet_properties(service, spreadsheet_id)

    if LEGACY_RAW_SHEET not in props:
        raise RuntimeError(
            f"NAVER_SEARCH_{year}에 {LEGACY_RAW_SHEET} 탭이 없습니다."
        )

    print("=" * 78)
    print(f"NAVER monthly migration v{APP_VERSION}")
    print(f"Year        : {year}")
    print(f"Source      : {LEGACY_RAW_SHEET}")
    print(f"Dry Run     : {dry_run}")
    print("=" * 78)

    # key: (scope_key, yyyy_mm) -> rows
    monthly_rows: dict[tuple[str, str], list[dict]] = defaultdict(list)

    source_data_rows = 0
    source_no_data_rows = 0
    ignored_rows = 0

    seen_rank_keys: dict[tuple[str, str, int], dict] = {}
    no_data_keys: dict[tuple[str, str], dict] = {}

    for raw in _read_raw_rows(service, spreadsheet_id):
        snapshot_date_raw = str(raw[0]).strip()

        try:
            snapshot_date = _parse_date(snapshot_date_raw)
        except Exception:
            ignored_rows += 1
            continue

        if snapshot_date.year != year:
            ignored_rows += 1
            continue

        rank_raw = str(raw[1]).strip()
        keyword = str(raw[2]).strip()
        category_id = str(raw[3]).strip()
        category_name = str(raw[4]).strip()
        collected_at = str(raw[5]).strip()
        scope_key_raw = str(raw[6]).strip()
        scope_name_raw = str(raw[7]).strip()

        resolved = scope_for_legacy_row(
            category_id=category_id,
            scope_key=scope_key_raw,
            scope_name=scope_name_raw,
        )

        if not resolved:
            ignored_rows += 1
            continue

        scope_key, scope_name = resolved
        scope = SCOPE_BY_KEY[scope_key]
        category_id = category_id or scope["category_id"]
        category_name = category_name or scope["category_name"]

        try:
            rank = int(float(rank_raw))
        except Exception:
            rank = None

        base = {
            "snapshot_date": snapshot_date.isoformat(),
            "rank": rank,
            "keyword": keyword,
            "category_id": category_id,
            "category_name": category_name,
            "collected_at": collected_at,
            "scope_key": scope_key,
            "scope_name": scope_name,
        }

        if rank is not None and keyword:
            source_data_rows += 1
            seen_rank_keys[
                (
                    snapshot_date.isoformat(),
                    scope_key,
                    rank,
                )
            ] = base
        else:
            source_no_data_rows += 1
            no_data_keys[
                (
                    snapshot_date.isoformat(),
                    scope_key,
                )
            ] = base

    # DATA가 있는 날짜/분류의 NO_DATA marker는 무시.
    data_date_scope = {
        (date_str, scope_key)
        for date_str, scope_key, _rank
        in seen_rank_keys.keys()
    }

    deduped_data_rows = list(seen_rank_keys.values())
    deduped_no_data = [
        row
        for key, row in no_data_keys.items()
        if key not in data_date_scope
    ]

    for row in deduped_data_rows:
        target_date = _parse_date(row["snapshot_date"])
        month_key = f"{target_date.year:04d}_{target_date.month:02d}"
        monthly_rows[
            (row["scope_key"], month_key)
        ].append(row)

    print(
        f"[SOURCE] data rows={source_data_rows:,} "
        f"-> deduped={len(deduped_data_rows):,}"
    )
    print(
        f"[SOURCE] no-data markers={source_no_data_rows:,} "
        f"-> deduped={len(deduped_no_data):,}"
    )
    print(f"[SOURCE] ignored rows={ignored_rows:,}")

    if dry_run:
        for (scope_key, month_key), rows in sorted(monthly_rows.items()):
            print(
                f"[DRY] {scope_key:20s} {month_key} "
                f"rows={len(rows):,}"
            )
        return

    meta_rows: list[list] = []
    written_data_rows = 0

    # 월×분류 탭 재생성
    for (scope_key, month_key), rows in sorted(
        monthly_rows.items(),
        key=lambda item: (
            item[0][1],
            SCOPE_ORDER.index(item[0][0]),
        ),
    ):
        scope = SCOPE_BY_KEY[scope_key]
        year_num, month_num = map(int, month_key.split("_"))
        sheet_name = monthly_sheet_name(
            scope_key,
            datetime(year_num, month_num, 1).date(),
        )

        rows.sort(
            key=lambda row: (
                row["snapshot_date"],
                int(row["rank"]),
                row["collected_at"],
            )
        )

        _ensure_sheet(
            service,
            spreadsheet_id,
            sheet_name,
            columns=len(DATA_HEADERS),
        )
        _clear_sheet_values(
            service,
            spreadsheet_id,
            sheet_name,
        )

        output = [DATA_HEADERS]
        current_row = 2

        # 날짜별로 row range 계산
        by_date: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            by_date[row["snapshot_date"]].append(row)

        for date_str in sorted(by_date):
            day_rows = by_date[date_str]
            start_row = current_row

            for row in day_rows:
                output.append(
                    [
                        row["snapshot_date"],
                        int(row["rank"]),
                        row["keyword"],
                        row["category_id"],
                        row["category_name"],
                        row["collected_at"],
                    ]
                )
                current_row += 1

            end_row = current_row - 1
            written_data_rows += len(day_rows)

            meta_rows.append(
                [
                    date_str,
                    scope_key,
                    scope["scope_name"],
                    sheet_name,
                    start_row,
                    end_row,
                    len(day_rows),
                    "DATA",
                    scope["category_id"],
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                ]
            )

        _write_values(
            service,
            spreadsheet_id,
            sheet_name,
            output,
            columns_end="F",
        )

        print(
            f"[WRITE] {sheet_name:24s} "
            f"rows={len(rows):,}"
        )

    # NO DATA는 실제 월 탭 row를 만들지 않고 META에만 기록.
    for row in deduped_no_data:
        target_date = _parse_date(row["snapshot_date"])
        scope = SCOPE_BY_KEY[row["scope_key"]]
        sheet_name = monthly_sheet_name(
            row["scope_key"],
            target_date,
        )

        meta_rows.append(
            [
                row["snapshot_date"],
                row["scope_key"],
                scope["scope_name"],
                sheet_name,
                "",
                "",
                0,
                "NO_DATA",
                scope["category_id"],
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ]
        )

    meta_rows.sort(
        key=lambda row: (
            row[0],
            SCOPE_ORDER.index(row[1]),
        )
    )

    _ensure_sheet(
        service,
        spreadsheet_id,
        META_SHEET,
        columns=len(META_HEADERS),
    )
    _clear_sheet_values(
        service,
        spreadsheet_id,
        META_SHEET,
    )
    _write_values(
        service,
        spreadsheet_id,
        META_SHEET,
        [META_HEADERS] + meta_rows,
        columns_end="J",
    )

    print()
    print("[VERIFY]")
    print(
        f"  source deduped DATA : {len(deduped_data_rows):,}"
    )
    print(
        f"  written monthly DATA: {written_data_rows:,}"
    )
    print(
        f"  META rows           : {len(meta_rows):,}"
    )

    if written_data_rows != len(deduped_data_rows):
        raise RuntimeError(
            "마이그레이션 검증 실패: 원본 DATA 행수와 "
            "월별 탭 DATA 행수가 일치하지 않습니다."
        )

    print()
    print("MIGRATION RESULT: SUCCESS")
    print(
        f"기존 {LEGACY_RAW_SHEET} 탭은 삭제하지 않았습니다. "
        "대시보드 검증 후 삭제하세요."
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "기존 NAVER_FOOD_KEYWORD_RAW를 "
            "월×분류 탭 + NAVER_META 구조로 변환"
        )
    )
    parser.add_argument(
        "year",
        type=int,
        help="마이그레이션 연도. 예: 2025",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="쓰기 없이 원본 구조/행수만 점검",
    )
    args = parser.parse_args()

    migrate_year(
        year=args.year,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
