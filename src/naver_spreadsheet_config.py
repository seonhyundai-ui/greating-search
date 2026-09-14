from __future__ import annotations

import os
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"

ENV_KEY_RE = re.compile(r"^NAVER_SEARCH_(\d{4})_ID$")

# 기존 2026 운영 파일은 즉시 계속 동작하도록 fallback 유지.
# 이후 연도는 .env / Streamlit Secrets에만 추가하면 된다.
LEGACY_FALLBACK_IDS = {
    2026: "1NlMzEVjsEbXGDILNEuY80RyexElJZRM9572EZpfDBxU",
}


def _read_local_env_file() -> dict[str, str]:
    """
    python-dotenv 의존성 없이 .env의 단순 KEY=VALUE만 읽는다.
    """
    if not ENV_FILE.exists():
        return {}

    result: dict[str, str] = {}

    for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if key:
            result[key] = value

    return result


def _streamlit_secret_values() -> dict[str, str]:
    try:
        import streamlit as st

        values: dict[str, str] = {}

        for key in st.secrets:
            key_str = str(key)

            if ENV_KEY_RE.match(key_str):
                value = str(st.secrets[key]).strip()
                if value:
                    values[key_str] = value

        return values
    except Exception:
        return {}


def get_spreadsheet_ids() -> dict[int, str]:
    """
    우선순위:
    1) 기존 2026 fallback
    2) 로컬 .env
    3) 실제 OS 환경변수
    4) Streamlit Secrets

    같은 연도 키가 여러 곳에 있으면 뒤쪽 값이 우선한다.
    """
    mapping = dict(LEGACY_FALLBACK_IDS)

    sources: list[dict[str, str]] = [
        _read_local_env_file(),
        {k: v for k, v in os.environ.items() if ENV_KEY_RE.match(k)},
        _streamlit_secret_values(),
    ]

    for source in sources:
        for key, value in source.items():
            match = ENV_KEY_RE.match(key)
            if not match:
                continue

            year = int(match.group(1))
            spreadsheet_id = str(value).strip()

            if spreadsheet_id:
                mapping[year] = spreadsheet_id

    return dict(sorted(mapping.items()))


def get_spreadsheet_id(year: int) -> str:
    mapping = get_spreadsheet_ids()

    if year not in mapping:
        raise RuntimeError(
            f"{year}년 NAVER_SEARCH Spreadsheet ID가 등록되지 않았습니다. "
            f".env 또는 Streamlit Secrets에 "
            f"NAVER_SEARCH_{year}_ID 값을 추가하세요."
        )

    return mapping[year]


def configured_years() -> list[int]:
    return sorted(get_spreadsheet_ids().keys())
