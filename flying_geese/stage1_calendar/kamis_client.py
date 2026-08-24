"""KAMIS(농산물유통정보) 오픈API 클라이언트.

https://www.kamis.or.kr 의 기간별 품목 도소매가격 API(action=periodProductList)를 감싼다.
실제 호출에는 KAMIS_CERT_KEY / KAMIS_CERT_ID 환경변수가 필요하다.
"""
from __future__ import annotations

from datetime import date, datetime

import requests

from flying_geese.config import Settings
from flying_geese.models import PriceRecord


class KamisClient:
    def __init__(self, settings: Settings, timeout: float = 10.0):
        self.settings = settings
        self.timeout = timeout

    def fetch_period_prices(
        self,
        item_code: str,
        kind_code: str,
        start_day: date,
        end_day: date,
        product_cls_code: str = "02",  # 02=소매, 01=도매
        category_code: str = "200",
    ) -> list[PriceRecord]:
        if not self.settings.kamis_ready():
            raise RuntimeError(
                "KAMIS_CERT_KEY / KAMIS_CERT_ID 환경변수가 설정되지 않았습니다."
            )

        params = {
            "action": "periodProductList",
            "p_productclscode": product_cls_code,
            "p_startday": start_day.isoformat(),
            "p_endday": end_day.isoformat(),
            "p_itemcategorycode": category_code,
            "p_itemcode": item_code,
            "p_kindcode": kind_code,
            "p_productrankcode": "04",
            "p_convert_kg_yn": "Y",
            "p_cert_key": self.settings.kamis_cert_key,
            "p_cert_id": self.settings.kamis_cert_id,
            "p_returntype": "json",
        }
        response = requests.get(self.settings.kamis_base_url, params=params, timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()
        return self._parse(payload)

    @staticmethod
    def _parse(payload: dict) -> list[PriceRecord]:
        items = payload.get("data", {}).get("item", [])
        records: list[PriceRecord] = []
        for row in items:
            price_raw = str(row.get("price", "0")).replace(",", "")
            try:
                price = float(price_raw)
            except ValueError:
                continue
            trade_date = _parse_kamis_date(row.get("yyyy"), row.get("regday"))
            if trade_date is None:
                continue
            records.append(
                PriceRecord(
                    # dict.get(key, default)는 키가 없을 때만 default를 쓴다.
                    # KAMIS는 일부 필드를 JSON null로 내려주는 경우가 있어
                    # `or` 폴백을 함께 써야 None으로 인한 크래시를 막을 수 있다.
                    product_code=str(row.get("itemcode") or ""),
                    product_name=(row.get("itemname") or "").strip(),
                    market=row.get("countyname") or "전국",
                    trade_date=trade_date,
                    price_per_unit=price,
                )
            )
        return records


def _parse_kamis_date(year: str | None, month_day: str | None) -> date | None:
    """KAMIS는 연도와 'MM/DD' 형태의 월일을 분리해서 내려준다."""
    if not year or not month_day:
        return None
    try:
        month_str, day_str = month_day.split("/")
        return date(int(year), int(month_str), int(day_str))
    except (ValueError, AttributeError):
        return None
