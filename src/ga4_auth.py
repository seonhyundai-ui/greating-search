from __future__ import annotations

from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow


ROOT = Path(__file__).resolve().parents[1]
CREDENTIALS_FILE = ROOT / "credentials.json"
TOKEN_FILE = ROOT / "token.json"

SCOPES = [
    "https://www.googleapis.com/auth/analytics.readonly",
    "https://www.googleapis.com/auth/webmasters.readonly",
]


def _streamlit_oauth_config() -> dict | None:
    """Return Streamlit Cloud OAuth secrets when present."""
    try:
        import streamlit as st

        oauth = st.secrets.get("google_oauth")
        if not oauth:
            return None

        return {
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
    except Exception:
        return None


def _cloud_credentials(config: dict) -> Credentials:
    required = [
        "refresh_token",
        "token_uri",
        "client_id",
        "client_secret",
    ]

    missing = [
        key
        for key in required
        if not config.get(key)
    ]

    if missing:
        raise RuntimeError(
            "Streamlit google_oauth Secrets가 비어 있습니다: "
            + ", ".join(missing)
        )

    creds = Credentials(
        token=None,
        refresh_token=config["refresh_token"],
        token_uri=config["token_uri"],
        client_id=config["client_id"],
        client_secret=config["client_secret"],
        scopes=SCOPES,
    )

    creds.refresh(Request())
    return creds


def _local_credentials() -> Credentials:
    creds = None

    if TOKEN_FILE.exists():
        try:
            creds = Credentials.from_authorized_user_file(
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

    if not creds or not creds.valid:
        if not CREDENTIALS_FILE.exists():
            raise RuntimeError(
                f"credentials.json 파일이 없습니다: {CREDENTIALS_FILE}"
            )

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


def get_credentials() -> Credentials:
    cloud_config = _streamlit_oauth_config()

    if cloud_config:
        return _cloud_credentials(cloud_config)

    return _local_credentials()
