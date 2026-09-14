from __future__ import annotations

from datetime import date

LEGACY_RAW_SHEET = "NAVER_FOOD_KEYWORD_RAW"
META_SHEET = "NAVER_META"

DATA_HEADERS = [
    "snapshot_date",
    "rank",
    "keyword",
    "category_id",
    "category_name",
    "collected_at",
]

META_HEADERS = [
    "snapshot_date",
    "scope_key",
    "scope_name",
    "sheet_name",
    "row_start",
    "row_end",
    "row_count",
    "status",
    "category_id",
    "updated_at",
]

SCOPES = [
    {
        "scope_key": "FOOD_ALL",
        "scope_name": "식품 전체",
        "category_id": "50000006",
        "category_name": "식품",
        "sheet_prefix": "FOOD",
    },
    {
        "scope_key": "FROZEN_CONVENIENCE",
        "scope_name": "냉동/간편조리식품",
        "category_id": "50000026",
        "category_name": "냉동/간편조리식품",
        "sheet_prefix": "FROZEN",
    },
    {
        "scope_key": "MEALKIT",
        "scope_name": "밀키트",
        "category_id": "50014240",
        "category_name": "밀키트",
        "sheet_prefix": "MEALKIT",
    },
    {
        "scope_key": "INSTANT_RICE_SOUP",
        "scope_name": "즉석밥/즉석국",
        "category_id": "50020779",
        "category_name": "즉석밥/즉석국",
        "sheet_prefix": "INSTANT",
    },
]

SCOPE_BY_KEY = {
    scope["scope_key"]: scope
    for scope in SCOPES
}

SCOPE_BY_CATEGORY_ID = {
    scope["category_id"]: scope
    for scope in SCOPES
}

SCOPE_ORDER = [
    scope["scope_key"]
    for scope in SCOPES
]

SCOPE_NAMES = {
    scope["scope_key"]: scope["scope_name"]
    for scope in SCOPES
}


def scope_for_legacy_row(
    category_id: str,
    scope_key: str,
    scope_name: str,
) -> tuple[str, str] | None:
    """
    기존 6컬럼 RAW는 category_id를 이용해 scope를 복원한다.
    새 8컬럼 RAW는 scope_key/scope_name을 그대로 우선한다.
    """
    normalized_key = str(scope_key or "").strip()
    normalized_name = str(scope_name or "").strip()
    normalized_category_id = str(category_id or "").strip()

    if normalized_key in SCOPE_BY_KEY:
        scope = SCOPE_BY_KEY[normalized_key]
        return normalized_key, normalized_name or scope["scope_name"]

    scope = SCOPE_BY_CATEGORY_ID.get(normalized_category_id)
    if scope:
        return scope["scope_key"], normalized_name or scope["scope_name"]

    return None


def monthly_sheet_name(
    scope_key: str,
    target_date: date,
) -> str:
    scope = SCOPE_BY_KEY[scope_key]
    return (
        f"{scope['sheet_prefix']}_"
        f"{target_date.year:04d}_{target_date.month:02d}"
    )
