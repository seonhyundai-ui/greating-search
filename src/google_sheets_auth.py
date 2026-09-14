from __future__ import annotations

from pathlib import Path

# 회사 Windows 환경에서 사내 루트 인증서를 사용하는 경우를 고려
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

from google.auth.credentials import Credentials
from google.oauth2.credentials import Credentials as UserCredentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

SPREADSHEETS_WRITE_SCOPE = "https://www.googleapis.com/auth/spreadsheets"

CREDENTIALS_FILE = Path("credentials.json")
TOKEN_FILE = Path("token_sheets.json")


def get_sheets_credentials() -> Credentials:
    """
    로컬 수집/적재 전용 Google Sheets OAuth.

    - GA4/Search Console token.json과 분리
    - token_sheets.json 사용
    - Google Sheets 쓰기 권한만 요청
    """
    creds: UserCredentials | None = None

    if TOKEN_FILE.exists():
        creds = UserCredentials.from_authorized_user_file(
            str(TOKEN_FILE),
            scopes=[SPREADSHEETS_WRITE_SCOPE],
        )

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())

    if not creds or not creds.valid:
        if not CREDENTIALS_FILE.exists():
            raise FileNotFoundError(
                f"{CREDENTIALS_FILE} 파일을 찾을 수 없습니다. "
                "greating-search 프로젝트 루트에 credentials.json을 두세요."
            )

        flow = InstalledAppFlow.from_client_secrets_file(
            str(CREDENTIALS_FILE),
            scopes=[SPREADSHEETS_WRITE_SCOPE],
        )
        creds = flow.run_local_server(port=0)

        TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")

    return creds
