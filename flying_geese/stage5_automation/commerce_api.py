"""Commerce API 연동 - 신규 주문 수집.

자사몰/카페24/고도몰 등 실제 커머스 플랫폼마다 API 스펙이 다르므로,
공통 인터페이스(CommerceClient)를 정의하고 REST 어댑터와 목(mock) 어댑터를 제공한다.
"""
from __future__ import annotations

from typing import Protocol

import requests

from flying_geese.config import Settings
from flying_geese.models import OrderLine, OrderStatus


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
        return [_parse_order(row) for row in response.json().get("orders", [])]

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


def _parse_order(row: dict) -> OrderLine:
    return OrderLine(
        order_id=str(row["orderId"]),
        product_name=row["productName"],
        variety_keyword=row.get("varietyKeyword", row["productName"]),
        quantity=int(row["quantity"]),
        unit_price=int(row["unitPrice"]),
        supplier_id=row.get("supplierId", ""),
        buyer_name=row.get("buyerName", ""),
        buyer_address=row.get("buyerAddress", ""),
        buyer_phone=row.get("buyerPhone", ""),
    )
