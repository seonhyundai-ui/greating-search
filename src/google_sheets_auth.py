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
CREDENTIALS_FILE = ROOT / "credentials.json"
TOKEN_FILE = ROOT / "token_sheets.json"
SERVICE_ACCOUNT_FILE = ROOT / "service_account_greating.json"

SPREADSHEETS_WRITE_SCOPE = "https://www.googleapis.com/auth/spreadsheets"

OAUTH_ENV_MAP = {
    "refresh_token": "GOOGLE_SHEETS_REFRESH_TOKEN",
    "token_uri": "GOOGLE_SHEETS_TOKEN_URI",
    "client_id": "GOOGLE_SHEETS_CLIENT_ID",
    "client_secret": "GOOGLE_SHEETS_CLIENT_SECRET",
}


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

    missing = [key for key in required if not str(info.get(key, "")).strip()]
    if missing:
        raise RuntimeError(
            "Google Service Account information is incomplete: "
            + ", ".join(missing)
        )

    return info


def _service_account_from_local_file():
    if not SERVICE_ACCOUNT_FILE.exists():
        return None

    return ServiceAccountCredentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=[SPREADSHEETS_WRITE_SCOPE],
    )


def _service_account_from_environment():
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        return None

    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON."
        ) from exc

    info = _normalize_service_account_info(info)

    return ServiceAccountCredentials.from_service_account_info(
        info,
        scopes=[SPREADSHEETS_WRITE_SCOPE],
    )


def _service_account_from_streamlit():
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
        scopes=[SPREADSHEETS_WRITE_SCOPE],
    )


def _oauth_from_environment():
    values = {
        key: os.environ.get(env_name, "").strip()
        for key, env_name in OAUTH_ENV_MAP.items()
    }

    if not any(values.values()):
        return None

    missing = [key for key, value in values.items() if not value]
    if missing:
        raise RuntimeError(
            "Google Sheets OAuth environment variables are incomplete: "
            + ", ".join(missing)
        )

    creds = UserCredentials(
        token=None,
        refresh_token=values["refresh_token"],
        token_uri=values["token_uri"],
        client_id=values["client_id"],
        client_secret=values["client_secret"],
        scopes=[SPREADSHEETS_WRITE_SCOPE],
    )
    creds.refresh(Request())
    return creds


def _oauth_from_streamlit():
    try:
        import streamlit as st
    except Exception:
        return None

    try:
        section = st.secrets.get("google_sheets_oauth")
    except Exception:
        return None

    if not section:
        return None

    values = {
        "refresh_token": str(section.get("refresh_token", "")).strip(),
        "token_uri": str(
            section.get(
                "token_uri",
                "https://oauth2.googleapis.com/token",
            )
        ).strip(),
        "client_id": str(section.get("client_id", "")).strip(),
        "client_secret": str(section.get("client_secret", "")).strip(),
    }

    missing = [key for key, value in values.items() if not value]
    if missing:
        raise RuntimeError(
            "Streamlit google_sheets_oauth Secrets are incomplete: "
            + ", ".join(missing)
        )

    creds = UserCredentials(
        token=None,
        refresh_token=values["refresh_token"],
        token_uri=values["token_uri"],
        client_id=values["client_id"],
        client_secret=values["client_secret"],
        scopes=[SPREADSHEETS_WRITE_SCOPE],
    )
    creds.refresh(Request())
    return creds


def _oauth_from_local_token():
    if not TOKEN_FILE.exists():
        return None

    try:
        creds = UserCredentials.from_authorized_user_file(
            TOKEN_FILE,
            [SPREADSHEETS_WRITE_SCOPE],
        )
    except Exception:
        return None

    if creds and not creds.has_scopes([SPREADSHEETS_WRITE_SCOPE]):
        return None

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception:
            return None

    if creds and creds.valid:
        return creds

    return None


def _oauth_from_local_interactive():
    if not CREDENTIALS_FILE.exists():
        return None

    flow = InstalledAppFlow.from_client_secrets_file(
        CREDENTIALS_FILE,
        [SPREADSHEETS_WRITE_SCOPE],
    )
    creds = flow.run_local_server(port=0)
    TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    return creds


def get_sheets_credentials():
    """
    Authentication priority:
      1. Local service_account_greating.json
      2. GOOGLE_SERVICE_ACCOUNT_JSON environment variable
      3. Streamlit [google_service_account]
      4. Existing GOOGLE_SHEETS_* OAuth environment variables
      5. Existing Streamlit [google_sheets_oauth]
      6. Existing local token_sheets.json
      7. Existing local credentials.json interactive OAuth

    Existing OAuth routes remain as fallback during migration.
    """
    loaders = [
        _service_account_from_local_file,
        _service_account_from_environment,
        _service_account_from_streamlit,
        _oauth_from_environment,
        _oauth_from_streamlit,
        _oauth_from_local_token,
        _oauth_from_local_interactive,
    ]

    errors: list[str] = []

    for loader in loaders:
        try:
            creds = loader()
        except Exception as exc:
            errors.append(f"{loader.__name__}: {type(exc).__name__}: {exc}")
            continue

        if creds is not None:
            return creds

    detail = "\n".join(errors)
    raise RuntimeError(
        "Google Sheets credentials were not found."
        + (f"\nErrors while trying auth methods:\n{detail}" if detail else "")
    )


def get_sheets_auth_source() -> str:
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

    if any(
        os.environ.get(env_name, "").strip()
        for env_name in OAUTH_ENV_MAP.values()
    ):
        return "oauth_environment"

    try:
        import streamlit as st
        if st.secrets.get("google_sheets_oauth"):
            return "oauth_streamlit"
    except Exception:
        pass

    if TOKEN_FILE.exists():
        return "oauth_local_token"

    if CREDENTIALS_FILE.exists():
        return "oauth_local_interactive"

    return "none"
