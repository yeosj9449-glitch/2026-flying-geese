"""aT 온라인도매시장(KAFB2B) 경락가 데이터 연동.

KAMIS가 커버하지 못하는 품목/공영도매시장의 경락가를 보완하기 위한 클라이언트다.
KAFB2B는 KAMIS의 periodProductList처럼 널리 공개된 표준 스펙이 없고 이용기관마다
계약을 통해 API 문서를 받는 형태이므로, AT_KAFB2B_BASE_URL/AT_KAFB2B_API_KEY로
운영자가 실제 엔드포인트를 지정하는 범용 REST 어댑터로 설계했다.

실제 연동 시에는 계약 시 발급받는 API 문서를 기준으로 `fetch_period_prices`의
엔드포인트 경로/쿼리 파라미터명과 `_parse_row`의 응답 필드명을 맞춰 조정해야 한다.
"""
from __future__ import annotations

import logging
from datetime import date

import requests

from flying_geese.config import Settings
from flying_geese.models import PriceRecord

logger = logging.getLogger(__name__)


class AtKafb2bClient:
    def __init__(self, settings: Settings, timeout: float = 10.0):
        self.settings = settings
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.settings.at_kafb2b_api_key}"}

    def fetch_period_prices(
        self, item_code: str, start_day: date, end_day: date
    ) -> list[PriceRecord]:
        """지정 기간의 공영도매시장 경락가 목록을 조회한다.

        아래 엔드포인트 경로("/auction-prices")와 파라미터명은 참고용 기본값이다.
        실제 계약된 API 스펙에 맞게 조정해서 사용한다.
        """
        if not self.settings.at_kafb2b_ready():
            raise RuntimeError(
                "AT_KAFB2B_API_KEY / AT_KAFB2B_BASE_URL 환경변수가 설정되지 않았습니다."
            )

        params = {
            "itemCode": item_code,
            "startDate": start_day.isoformat(),
            "endDate": end_day.isoformat(),
        }
        response = requests.get(
            f"{self.settings.at_kafb2b_base_url}/auction-prices",
            params=params,
            headers=self._headers(),
            timeout=self.timeout,
        )
        response.raise_for_status()
        return self._parse_rows(response.json().get("items", []))

    @classmethod
    def _parse_rows(cls, rows: list[dict]) -> list[PriceRecord]:
        """행 하나가 malformed이어도 그 한 건만 건너뛰고 나머지는 반환한다."""
        records: list[PriceRecord] = []
        for row in rows:
            record = cls._parse_row(row)
            if record is not None:
                records.append(record)
            else:
                logger.warning("KAFB2B 경락가 파싱 실패, 건너뜁니다: %r", row)
        return records

    @staticmethod
    def _parse_row(row: dict) -> PriceRecord | None:
        try:
            trade_date = date.fromisoformat(row["tradeDate"])
            price = float(str(row.get("price") or "0").replace(",", ""))
        except (KeyError, ValueError, TypeError):
            return None
        return PriceRecord(
            product_code=str(row.get("itemCode") or ""),
            product_name=(row.get("itemName") or "").strip(),
            market=row.get("marketName") or "전국",
            trade_date=trade_date,
            price_per_unit=price,
        )
