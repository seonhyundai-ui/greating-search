from __future__ import annotations

import argparse
import time
from datetime import datetime

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

import pandas as pd
import requests

APP_VERSION = "0.2.0"

NAVER_RANK_URL = "https://datalab.naver.com/shoppingInsight/getCategoryKeywordRank.naver"
REFERER = "https://datalab.naver.com/shoppingInsight/sCategory.naver"

DEFAULT_CATEGORY_ID = "50000006"
DEFAULT_CATEGORY_NAME = "식품"

PAGE_SIZE = 20
MAX_PAGES = 25
REQUEST_DELAY_SEC = 0.4
REQUEST_TIMEOUT_SEC = 20


def _headers() -> dict[str, str]:
    return {
        "Referer": REFERER,
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/152.0.0.0 Safari/537.36"
        ),
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
    }


def fetch_food_keyword_rank(
    target_date: str,
    category_id: str = DEFAULT_CATEGORY_ID,
    category_name: str = DEFAULT_CATEGORY_NAME,
    max_pages: int = MAX_PAGES,
    request_delay_sec: float = REQUEST_DELAY_SEC,
) -> pd.DataFrame:
    """
    NAVER DataLab 쇼핑인사이트 특정 카테고리 인기검색어 TOP 500 조회.

    기본값은 1분류 '식품'.
    category_id/category_name을 전달하면 2분류도 동일하게 조회한다.

    주의:
    NAVER DataLab 웹 화면의 내부 요청을 사용하므로
    네이버 화면 구조가 변경되면 수정이 필요할 수 있다.
    """
    datetime.strptime(target_date, "%Y-%m-%d")

    rows: list[dict] = []
    session = requests.Session()
    session.headers.update(_headers())

    for page in range(1, max_pages + 1):
        payload = {
            "cid": str(category_id),
            "timeUnit": "date",
            "startDate": target_date,
            "endDate": target_date,
            "age": "",
            "gender": "",
            "device": "",
            "page": page,
            "count": PAGE_SIZE,
        }

        try:
            response = session.post(
                NAVER_RANK_URL,
                data=payload,
                timeout=REQUEST_TIMEOUT_SEC,
            )
        except requests.exceptions.SSLError as exc:
            raise RuntimeError(
                "SSL certificate verification failed. "
                "회사 보안 프록시/사설 루트 인증서 환경일 가능성이 높습니다. "
                "`truststore` 설치 상태를 확인하세요."
            ) from exc

        if response.status_code != 200:
            raise RuntimeError(
                f"NAVER DataLab request failed: "
                f"category={category_name}({category_id}), "
                f"page={page}, status={response.status_code}, "
                f"body={response.text[:300]}"
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise RuntimeError(
                f"NAVER DataLab returned non-JSON response: "
                f"category={category_name}({category_id}), "
                f"page={page}, body={response.text[:300]}"
            ) from exc

        ranks = body.get("ranks", [])

        if not ranks:
            if page == 1:
                raise RuntimeError(
                    f"No ranking data returned for {target_date}. "
                    f"category={category_name}({category_id}). "
                    "해당 날짜 데이터가 아직 제공되지 않았거나 "
                    "NAVER DataLab 응답 구조가 변경되었을 수 있습니다."
                )
            break

        for index, item in enumerate(ranks, start=1):
            keyword = str(item.get("keyword", "")).strip()

            if not keyword:
                continue

            raw_rank = item.get("rank")

            if raw_rank is None:
                rank = (page - 1) * PAGE_SIZE + index
            else:
                try:
                    rank = int(raw_rank)
                except (TypeError, ValueError):
                    rank = (page - 1) * PAGE_SIZE + index

            rows.append(
                {
                    "snapshot_date": target_date,
                    "rank": rank,
                    "keyword": keyword,
                    "category_id": str(category_id),
                    "category_name": str(category_name),
                    "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
            )

        print(
            f"[NAVER] {category_name} | "
            f"page={page:02d}/{max_pages:02d} "
            f"rows={len(ranks):02d} total={len(rows):03d}"
        )

        if page < max_pages:
            time.sleep(request_delay_sec)

    df = pd.DataFrame(rows)

    if df.empty:
        raise RuntimeError(
            f"NAVER DataLab ranking result is empty. "
            f"category={category_name}({category_id})"
        )

    df = (
        df.sort_values(["rank", "keyword"])
        .drop_duplicates(
            subset=["snapshot_date", "rank"],
            keep="first",
        )
        .reset_index(drop=True)
    )

    return df


def main() -> None:
    parser = argparse.ArgumentParser(
        description="NAVER DataLab 카테고리 인기검색어 TOP 500 조회 테스트"
    )
    parser.add_argument("target_date", help="조회 날짜 YYYY-MM-DD")
    parser.add_argument(
        "--category-id",
        default=DEFAULT_CATEGORY_ID,
        help="NAVER DataLab category id",
    )
    parser.add_argument(
        "--category-name",
        default=DEFAULT_CATEGORY_NAME,
        help="표시용 카테고리명",
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=MAX_PAGES,
        help="조회 페이지 수. 기본 25 = TOP 500",
    )
    args = parser.parse_args()

    print("=" * 72)
    print(f"NAVER Keyword Rank Collector v{APP_VERSION}")
    print(f"Target Date : {args.target_date}")
    print(f"Category    : {args.category_name} ({args.category_id})")
    print(f"Pages       : {args.pages}")
    print("=" * 72)

    df = fetch_food_keyword_rank(
        target_date=args.target_date,
        category_id=args.category_id,
        category_name=args.category_name,
        max_pages=args.pages,
    )

    print()
    print("[TOP 20]")
    print(df[["rank", "keyword"]].head(20).to_string(index=False))
    print()
    print(f"[SUCCESS] rows={len(df):,}")


if __name__ == "__main__":
    main()
