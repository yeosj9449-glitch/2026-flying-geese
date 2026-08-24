"""네이버 데이터랩 검색어 트렌드 API 클라이언트.

https://openapi.naver.com/v1/datalab/search
NAVER_DATALAB_CLIENT_ID / NAVER_DATALAB_CLIENT_SECRET 환경변수가 필요하다.
"""
from __future__ import annotations

from datetime import date

import requests

from flying_geese.config import Settings

DATALAB_URL = "https://openapi.naver.com/v1/datalab/search"


class NaverDatalabClient:
    def __init__(self, settings: Settings, timeout: float = 10.0):
        self.settings = settings
        self.timeout = timeout

    def search_trend(
        self,
        keywords: list[str],
        start_date: date,
        end_date: date,
        time_unit: str = "month",
    ) -> dict:
        if not self.settings.naver_datalab_ready():
            raise RuntimeError(
                "NAVER_DATALAB_CLIENT_ID / NAVER_DATALAB_CLIENT_SECRET 환경변수가 설정되지 않았습니다."
            )

        headers = {
            "X-Naver-Client-Id": self.settings.naver_datalab_client_id,
            "X-Naver-Client-Secret": self.settings.naver_datalab_client_secret,
            "Content-Type": "application/json",
        }
        body = {
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "timeUnit": time_unit,
            "keywordGroups": [
                {"groupName": kw, "keywords": [kw]} for kw in keywords
            ],
        }
        response = requests.post(DATALAB_URL, headers=headers, json=body, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def latest_ratio_by_keyword(datalab_response: dict) -> dict[str, float]:
        """각 키워드 그룹의 가장 최근 구간 상대 검색 비율(ratio)을 추출한다."""
        result: dict[str, float] = {}
        for group in datalab_response.get("results", []):
            data_points = group.get("data", [])
            if data_points:
                # ratio가 JSON null로 내려오는 구간이 있을 수 있어 `or` 폴백을 쓴다.
                # get(key, default)는 키가 존재하되 값이 None일 때는 default를
                # 적용하지 않으므로 float(None)에서 크래시가 날 수 있다.
                result[group["title"]] = float(data_points[-1].get("ratio") or 0.0)
        return result
