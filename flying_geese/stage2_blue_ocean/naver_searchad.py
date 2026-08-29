"""네이버 검색광고(SearchAd) API - 연관키워드/월간 검색량 조회.

https://api.searchad.naver.com/keywordstool
서명은 timestamp + method + uri 를 secret key로 HMAC-SHA256 후 base64 인코딩한다.
NAVER_SEARCHAD_API_KEY / NAVER_SEARCHAD_SECRET_KEY / NAVER_SEARCHAD_CUSTOMER_ID 필요.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time

import requests

from flying_geese.config import Settings

SEARCHAD_BASE_URL = "https://api.searchad.naver.com"
KEYWORDS_TOOL_URI = "/keywordstool"


class NaverSearchAdClient:
    def __init__(self, settings: Settings, timeout: float = 10.0):
        self.settings = settings
        self.timeout = timeout

    def _signature(self, timestamp: str, method: str, uri: str) -> str:
        message = f"{timestamp}.{method}.{uri}"
        digest = hmac.new(
            self.settings.naver_searchad_secret_key.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return base64.b64encode(digest).decode("utf-8")

    def _headers(self, method: str, uri: str) -> dict[str, str]:
        timestamp = str(int(time.time() * 1000))
        return {
            "X-Timestamp": timestamp,
            "X-API-KEY": self.settings.naver_searchad_api_key,
            "X-Customer": self.settings.naver_searchad_customer_id,
            "X-Signature": self._signature(timestamp, method, uri),
        }

    def keyword_stats(self, hint_keywords: list[str]) -> list[dict]:
        """연관키워드의 월간 PC+모바일 검색량 및 경쟁 정도를 조회한다."""
        if not self.settings.naver_searchad_ready():
            raise RuntimeError(
                "NAVER_SEARCHAD_API_KEY / SECRET_KEY / CUSTOMER_ID 환경변수가 설정되지 않았습니다."
            )

        params = {"hintKeywords": ",".join(hint_keywords), "showDetail": "1"}
        headers = self._headers("GET", KEYWORDS_TOOL_URI)
        response = requests.get(
            SEARCHAD_BASE_URL + KEYWORDS_TOOL_URI,
            params=params,
            headers=headers,
            timeout=self.timeout,
        )
        if not response.ok:
            raise RuntimeError(
                f"네이버 검색광고 API 오류 {response.status_code}: {response.text}"
            )
        return response.json().get("keywordList", [])

    @staticmethod
    def monthly_search_volume(keyword_row: dict) -> int:
        def _to_int(value) -> int:
            if isinstance(value, str) and value.startswith("<"):
                return 0
            try:
                return int(value)
            except (TypeError, ValueError):
                return 0

        pc = _to_int(keyword_row.get("monthlyPcQcCnt", 0))
        mobile = _to_int(keyword_row.get("monthlyMobileQcCnt", 0))
        return pc + mobile
