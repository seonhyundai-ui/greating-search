from __future__ import annotations

import json
from typing import Any

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

import requests

APP_VERSION = "0.1.0"

ROOT_CID = "50000006"
TARGET_NAMES = {
    "냉동/간편조리식품",
    "밀키트",
    "즉석밥/즉석국",
}

CATEGORY_URL = "https://datalab.naver.com/shoppingInsight/getCategory.naver"
REFERER = "https://datalab.naver.com/shoppingInsight/sCategory.naver"

HEADERS = {
    "Referer": REFERER,
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/152.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
}

ID_KEYS = (
    "cid",
    "id",
    "categoryId",
    "category_id",
    "categoryNo",
    "category_no",
)

NAME_KEYS = (
    "name",
    "categoryName",
    "category_name",
    "title",
)


def fetch_category(cid: str) -> Any:
    response = requests.get(
        CATEGORY_URL,
        params={"cid": cid},
        headers=HEADERS,
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def walk(obj: Any, path: tuple[str, ...] = ()):
    if isinstance(obj, dict):
        name = None
        cid = None

        for key in NAME_KEYS:
            if key in obj and isinstance(obj[key], (str, int)):
                name = str(obj[key]).strip()
                break

        for key in ID_KEYS:
            if key in obj and isinstance(obj[key], (str, int)):
                cid = str(obj[key]).strip()
                break

        next_path = path
        if name:
            next_path = path + (name,)
            yield {
                "name": name,
                "cid": cid,
                "path": " > ".join(next_path),
            }

        for value in obj.values():
            yield from walk(value, next_path)

    elif isinstance(obj, list):
        for item in obj:
            yield from walk(item, path)


def main() -> None:
    print("=" * 72)
    print(f"NAVER DataLab Category Probe v{APP_VERSION}")
    print(f"Root CID: {ROOT_CID} (식품)")
    print("=" * 72)

    body = fetch_category(ROOT_CID)

    print("\n[RAW RESPONSE]")
    print(json.dumps(body, ensure_ascii=False, indent=2))

    found = list(walk(body))

    print("\n[PARSED CATEGORY CANDIDATES]")
    if not found:
        print("No candidates parsed.")
    else:
        for item in found:
            print(
                f"name={item['name']} | cid={item['cid']} | path={item['path']}"
            )

    print("\n[TARGET MATCHES]")
    matches = [
        item for item in found
        if item["name"] in TARGET_NAMES
    ]

    if not matches:
        print("No target matches found in this response.")
        print("이 경우 2분류 아래 하위 카테고리는 추가 조회가 필요합니다.")
    else:
        for item in matches:
            print(
                f"{item['name']} | cid={item['cid']} | path={item['path']}"
            )


if __name__ == "__main__":
    main()
