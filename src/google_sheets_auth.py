from __future__ import annotations

import os
from pathlib import Path

# 회사 Windows 환경에서 사내 루트 인증서를 사용하는 경우를 고려
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

from google.auth.credentials import Credentials
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials as UserCredentials
from google_auth_oauthlib.flow import InstalledAppFlow

APP_VERSION = "0.2.0"

SPREADSHEETS_WRITE_SCOPE = (
    "https://www.googleapis.com/auth/spreadsheets"
)

CREDENTIALS_FILE = Path("credentials.json")
TOKEN_FILE = Path("token_sheets.json")

ENV_KEYS = {
    "refresh_token": "GOOGLE_SHEETS_REFRESH_TOKEN",
    "token_uri": "GOOGLE_SHEETS_TOKEN_URI",
    "client_id": "GOOGLE_SHEETS_CLIENT_ID",
    "client_secret": "GOOGLE_SHEETS_CLIENT_SECRET",
}


def _credentials_from_mapping(
    values: dict[str, str],
) -> UserCredentials | None:
    required = (
        "refresh_token",
        "token_uri",
        "client_id",
        "client_secret",
    )

    if not all(
        str(values.get(key, "")).strip()
        for key in required
    ):
        return None

    creds = UserCredentials(
        token=None,
        refresh_token=str(values["refresh_token"]).strip(),
        token_uri=str(values["token_uri"]).strip(),
        client_id=str(values["client_id"]).strip(),
        client_secret=str(values["client_secret"]).strip(),
        scopes=[SPREADSHEETS_WRITE_SCOPE],
    )

    # token=None 상태에서도 refresh_token으로 즉시 access token 발급.
    creds.refresh(Request())
    return creds


def _credentials_from_environment() -> UserCredentials | None:
    values = {
        field: os.environ.get(env_name, "")
        for field, env_name in ENV_KEYS.items()
    }
    return _credentials_from_mapping(values)


def _credentials_from_streamlit() -> UserCredentials | None:
    """
    Streamlit Cloud:
      [google_sheets_oauth]
      refresh_token = "..."
      token_uri = "..."
      client_id = "..."
      client_secret = "..."
    """
    try:
        import streamlit as st

        if "google_sheets_oauth" not in st.secrets:
            return None

        section = st.secrets["google_sheets_oauth"]

        values = {
            "refresh_token": section.get("refresh_token", ""),
            "token_uri": section.get("token_uri", ""),
            "client_id": section.get("client_id", ""),
            "client_secret": section.get("client_secret", ""),
        }

        return _credentials_from_mapping(values)
    except Exception:
        return None


def _credentials_from_local_token() -> UserCredentials | None:
    if not TOKEN_FILE.exists():
        return None

    creds = UserCredentials.from_authorized_user_file(
        str(TOKEN_FILE),
        scopes=[SPREADSHEETS_WRITE_SCOPE],
    )

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())

    if creds.valid:
        return creds

    return None


def _run_local_oauth() -> UserCredentials:
    if not CREDENTIALS_FILE.exists():
        raise FileNotFoundError(
            f"{CREDENTIALS_FILE} 파일을 찾을 수 없습니다. "
            "로컬 실행은 프로젝트 루트에 credentials.json을 두고, "
            "Streamlit Cloud는 [google_sheets_oauth], "
            "GitHub Actions는 GOOGLE_SHEETS_* Secrets를 사용하세요."
        )

    flow = InstalledAppFlow.from_client_secrets_file(
        str(CREDENTIALS_FILE),
        scopes=[SPREADSHEETS_WRITE_SCOPE],
    )

    creds = flow.run_local_server(port=0)
    TOKEN_FILE.write_text(
        creds.to_json(),
        encoding="utf-8",
    )
    return creds


def get_sheets_credentials() -> Credentials:
    """
    Google Sheets 쓰기 OAuth 우선순위

    1. OS 환경변수
       - GitHub Actions Secrets가 env로 주입됨
    2. Streamlit Secrets [google_sheets_oauth]
       - Streamlit Cloud의 수동 적재 버튼
    3. 로컬 token_sheets.json
       - Windows 로컬 수집
    4. credentials.json OAuth 로그인
       - 로컬 최초 인증
    """
    for loader in (
        _credentials_from_environment,
        _credentials_from_streamlit,
        _credentials_from_local_token,
    ):
        creds = loader()
        if creds is not None:
            return creds

    return _run_local_oauth()
