"""네이버 쇼핑 검색 API - 키워드별 등록 상품 수(total) 조회 → 포화도 산정.

https://openapi.naver.com/v1/search/shop.json
네이버 개발자센터 애플리케이션에서 '검색' API 사용을 추가로 체크하면, 데이터랩과
같은 Client ID/Secret(NAVER_DATALAB_CLIENT_ID/SECRET)으로 호출할 수 있다.
일 호출 한도가 있으므로 A/B 등급 후보에만 조회한다.
"""
from __future__ import annotations

import time

import requests

from flying_geese.config import Settings

SHOP_SEARCH_URL = "https://openapi.naver.com/v1/search/shop.json"


class NaverShoppingClient:
    def __init__(self, settings: Settings, timeout: float = 10.0):
        self.settings = settings
        self.timeout = timeout

    def product_count(self, keyword: str) -> int:
        if not self.settings.naver_datalab_ready():
            raise RuntimeError("NAVER_DATALAB_CLIENT_ID / SECRET 환경변수가 설정되지 않았습니다.")
        response = requests.get(
            SHOP_SEARCH_URL,
            params={"query": keyword, "display": 1},
            headers={
                "X-Naver-Client-Id": self.settings.naver_datalab_client_id,
                "X-Naver-Client-Secret": self.settings.naver_datalab_client_secret,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return self.parse_total(response.json())

    @staticmethod
    def parse_total(payload: dict) -> int:
        return int(payload.get("total") or 0)

    def product_counts(self, keywords: list[str], pause_sec: float = 0.15) -> dict[str, int]:
        """키워드 하나가 실패해도 나머지는 계속 조회한다."""
        counts: dict[str, int] = {}
        for keyword in keywords:
            try:
                counts[keyword] = self.product_count(keyword)
            except Exception as exc:  # noqa: BLE001
                print(f"[shopping] '{keyword}' 상품 수 조회 실패: {exc}")
            time.sleep(pause_sec)
        return counts
