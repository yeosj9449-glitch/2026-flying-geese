"""농가 발송 송장 번호 수집 -> 발송 처리 API 자동 호출 및 배송 상태 모니터링."""
from __future__ import annotations

import csv
from pathlib import Path

from flying_geese.models import OrderLine, OrderStatus
from flying_geese.stage5_automation.commerce_api import CommerceClient


def load_tracking_numbers_from_csv(path: str | Path) -> dict[str, str]:
    """농가에서 회신한 'order_id,tracking_number' 형식의 CSV를 읽는다."""
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"송장 CSV 파일을 찾을 수 없습니다: {file_path}")

    tracking_map: dict[str, str] = {}
    with file_path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            order_id = row.get("order_id", "").strip()
            tracking_number = row.get("tracking_number", "").strip()
            if order_id and tracking_number:
                tracking_map[order_id] = tracking_number
    return tracking_map


def dispatch_orders(
    orders: list[OrderLine],
    tracking_map: dict[str, str],
    client: CommerceClient,
) -> tuple[list[OrderLine], list[str]]:
    """송장 번호가 수집된 주문에 대해 발송 처리 API를 호출하고 상태를 갱신한다.

    이미 NEW 상태가 아닌 주문(이미 발송 처리됐거나 취소된 건)은 재처리하지
    않는다. 송장 CSV가 누적/재업로드되는 운영 환경에서 이 가드가 없으면
    이미 발송 처리된 주문에 대해 발송 API가 다시 호출되어 고객에게 중복
    발송 알림이 갈 수 있다.
    """
    dispatched: list[OrderLine] = []
    missing: list[str] = []

    for order in orders:
        if order.status != OrderStatus.NEW:
            continue
        tracking_number = tracking_map.get(order.order_id)
        if not tracking_number:
            missing.append(order.order_id)
            continue
        client.mark_dispatched(order.order_id, tracking_number)
        order.tracking_number = tracking_number
        order.status = OrderStatus.SHIPPED
        dispatched.append(order)

    return dispatched, missing


def shipping_status_summary(orders: list[OrderLine]) -> dict[str, int]:
    summary: dict[str, int] = {status.value: 0 for status in OrderStatus}
    for order in orders:
        summary[order.status.value] += 1
    return summary
