"""Commerce API 연동 - 신규 주문 수집.

자사몰/카페24/고도몰 등 실제 커머스 플랫폼마다 API 스펙이 다르므로,
공통 인터페이스(CommerceClient)를 정의하고 REST 어댑터와 목(mock) 어댑터를 제공한다.
"""
from __future__ import annotations

import logging
from typing import Protocol

import requests

from flying_geese.config import Settings
from flying_geese.models import OrderLine, OrderStatus

logger = logging.getLogger(__name__)


class CommerceClient(Protocol):
    def fetch_new_orders(self) -> list[OrderLine]:
        ...

    def mark_dispatched(self, order_id: str, tracking_number: str) -> None:
        ...


class RestCommerceClient:
    """설정된 COMMERCE_API_BASE_URL을 사용하는 범용 REST 어댑터."""

    def __init__(self, settings: Settings, timeout: float = 10.0):
        self.settings = settings
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.settings.commerce_api_key}"}

    def fetch_new_orders(self) -> list[OrderLine]:
        if not self.settings.commerce_api_base_url:
            raise RuntimeError("COMMERCE_API_BASE_URL 환경변수가 설정되지 않았습니다.")

        response = requests.get(
            f"{self.settings.commerce_api_base_url}/orders",
            params={"status": "NEW"},
            headers=self._headers(),
            timeout=self.timeout,
        )
        response.raise_for_status()
        return _parse_orders(response.json().get("orders", []))

    def mark_dispatched(self, order_id: str, tracking_number: str) -> None:
        response = requests.post(
            f"{self.settings.commerce_api_base_url}/orders/{order_id}/dispatch",
            json={"trackingNumber": tracking_number},
            headers=self._headers(),
            timeout=self.timeout,
        )
        response.raise_for_status()


class MockCommerceClient:
    """실제 API 키 없이 파이프라인을 검증하기 위한 인메모리 어댑터."""

    def __init__(self, orders: list[OrderLine]):
        self._orders = {o.order_id: o for o in orders}

    def fetch_new_orders(self) -> list[OrderLine]:
        return [o for o in self._orders.values() if o.status == OrderStatus.NEW]

    def mark_dispatched(self, order_id: str, tracking_number: str) -> None:
        order = self._orders.get(order_id)
        if order is None:
            raise KeyError(f"존재하지 않는 주문입니다: {order_id}")
        order.tracking_number = tracking_number
        order.status = OrderStatus.SHIPPED


def _parse_orders(rows: list[dict]) -> list[OrderLine]:
    """주문 목록을 파싱한다. 개별 주문이 malformed(필수 필드 누락/null)이어도
    그 한 건만 건너뛰고 나머지 정상 주문은 그대로 처리한다.

    한 건이라도 파싱에 실패하면 전체 fetch가 예외로 죽어 그날의 모든 정상
    주문까지 발주서/배송 처리로 못 넘어가는 것을 방지한다.
    """
    orders: list[OrderLine] = []
    for row in rows:
        try:
            orders.append(_parse_order(row))
        except (KeyError, TypeError, ValueError):
            logger.warning("주문 파싱 실패, 건너뜁니다: %r", row)
    return orders


def _parse_order(row: dict) -> OrderLine:
    product_name = row["productName"]
    return OrderLine(
        order_id=str(row["orderId"]),
        product_name=product_name,
        variety_keyword=row.get("varietyKeyword") or product_name,
        quantity=int(row["quantity"]),
        unit_price=int(row["unitPrice"]),
        supplier_id=row.get("supplierId") or "",
        buyer_name=row.get("buyerName") or "",
        buyer_address=row.get("buyerAddress") or "",
        buyer_phone=row.get("buyerPhone") or "",
    )
