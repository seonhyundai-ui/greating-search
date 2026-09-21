from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials as UserCredentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from google_auth_oauthlib.flow import InstalledAppFlow


AUTH_VERSION = "0.3.0"

ROOT = Path(__file__).resolve().parents[1]

# 기존 OAuth 파일
CREDENTIALS_FILE = ROOT / "credentials.json"
TOKEN_FILE = ROOT / "token.json"

# 신규 서비스 계정 파일
SERVICE_ACCOUNT_FILE = ROOT / "service_account_greating.json"

SCOPES = [
    "https://www.googleapis.com/auth/analytics.readonly",
    "https://www.googleapis.com/auth/webmasters.readonly",
]


def _normalize_service_account_info(values: dict[str, Any]) -> dict[str, Any]:
    info = {str(k): v for k, v in dict(values).items()}

    if "private_key" in info and info["private_key"] is not None:
        private_key = str(info["private_key"])
        if "\\n" in private_key and "\n" not in private_key:
            private_key = private_key.replace("\\n", "\n")
        info["private_key"] = private_key

    required = [
        "type",
        "project_id",
        "private_key_id",
        "private_key",
        "client_email",
        "client_id",
        "token_uri",
    ]

    missing = [
        key
        for key in required
        if not str(info.get(key, "")).strip()
    ]

    if missing:
        raise RuntimeError(
            "Google Service Account 정보가 불완전합니다: "
            + ", ".join(missing)
        )

    return info


def _service_account_from_local_file():
    if not SERVICE_ACCOUNT_FILE.exists():
        return None

    return ServiceAccountCredentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=SCOPES,
    )


def _service_account_from_environment():
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()

    if not raw:
        return None

    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "GOOGLE_SERVICE_ACCOUNT_JSON이 올바른 JSON이 아닙니다."
        ) from exc

    info = _normalize_service_account_info(info)

    return ServiceAccountCredentials.from_service_account_info(
        info,
        scopes=SCOPES,
    )


def _service_account_from_streamlit():
    """
    Streamlit Cloud에서는 Secrets의 [google_service_account] 섹션을 사용한다.
    service_account_greating.json의 키/값을 그대로 옮기면 된다.
    """
    try:
        import streamlit as st
    except Exception:
        return None

    try:
        section = st.secrets.get("google_service_account")
    except Exception:
        return None

    if not section:
        return None

    info = _normalize_service_account_info(dict(section))

    return ServiceAccountCredentials.from_service_account_info(
        info,
        scopes=SCOPES,
    )


def _oauth_from_streamlit():
    try:
        import streamlit as st
    except Exception:
        return None

    try:
        oauth = st.secrets.get("google_oauth")
    except Exception:
        return None

    if not oauth:
        return None

    values = {
        "refresh_token": str(oauth.get("refresh_token", "")).strip(),
        "token_uri": str(
            oauth.get(
                "token_uri",
                "https://oauth2.googleapis.com/token",
            )
        ).strip(),
        "client_id": str(oauth.get("client_id", "")).strip(),
        "client_secret": str(oauth.get("client_secret", "")).strip(),
    }

    missing = [
        key
        for key, value in values.items()
        if not value
    ]

    if missing:
        raise RuntimeError(
            "Streamlit google_oauth Secrets가 불완전합니다: "
            + ", ".join(missing)
        )

    creds = UserCredentials(
        token=None,
        refresh_token=values["refresh_token"],
        token_uri=values["token_uri"],
        client_id=values["client_id"],
        client_secret=values["client_secret"],
        scopes=SCOPES,
    )

    creds.refresh(Request())
    return creds


def _oauth_from_local_token():
    creds = None

    if TOKEN_FILE.exists():
        try:
            creds = UserCredentials.from_authorized_user_file(
                TOKEN_FILE,
                SCOPES,
            )
        except Exception:
            creds = None

    if creds and not creds.has_scopes(SCOPES):
        creds = None

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception:
            creds = None

    if creds and creds.valid:
        return creds

    return None


def _oauth_from_local_interactive():
    if not CREDENTIALS_FILE.exists():
        return None

    flow = InstalledAppFlow.from_client_secrets_file(
        CREDENTIALS_FILE,
        SCOPES,
    )

    creds = flow.run_local_server(port=0)

    TOKEN_FILE.write_text(
        creds.to_json(),
        encoding="utf-8",
    )

    return creds


def get_credentials():
    """
    GA4 / Search Console 인증 우선순위

    1) 로컬 service_account_greating.json
    2) GOOGLE_SERVICE_ACCOUNT_JSON 환경변수
    3) Streamlit [google_service_account]
    4) 기존 Streamlit [google_oauth]
    5) 기존 로컬 token.json
    6) 기존 로컬 credentials.json 대화형 인증
    """
    loaders = [
        _service_account_from_local_file,
        _service_account_from_environment,
        _service_account_from_streamlit,
        _oauth_from_streamlit,
        _oauth_from_local_token,
        _oauth_from_local_interactive,
    ]

    errors: list[str] = []

    for loader in loaders:
        try:
            creds = loader()
        except Exception as exc:
            errors.append(
                f"{loader.__name__}: {type(exc).__name__}: {exc}"
            )
            continue

        if creds is not None:
            return creds

    detail = "\n".join(errors)

    raise RuntimeError(
        "GA4/Search Console 인증 정보를 찾을 수 없습니다."
        + (f"\n시도 중 발생한 오류:\n{detail}" if detail else "")
    )


def get_ga4_auth_source() -> str:
    if SERVICE_ACCOUNT_FILE.exists():
        return "service_account_local_file"

    if os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip():
        return "service_account_environment"

    try:
        import streamlit as st
        if st.secrets.get("google_service_account"):
            return "service_account_streamlit"
    except Exception:
        pass

    try:
        import streamlit as st
        if st.secrets.get("google_oauth"):
            return "oauth_streamlit"
    except Exception:
        pass

    if TOKEN_FILE.exists():
        return "oauth_local_token"

    if CREDENTIALS_FILE.exists():
        return "oauth_local_interactive"

    return "none"
