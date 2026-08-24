from flying_geese.models import OrderLine, OrderStatus
from flying_geese.stage5_automation.commerce_api import MockCommerceClient
from flying_geese.stage5_automation.shipping import dispatch_orders, shipping_status_summary


def test_dispatch_orders_marks_shipped_and_reports_missing():
    orders = [
        OrderLine("ORD-1", "고구마", "베니하르카 호박고구마", 2, 32000, "S1", "김민준", "서울시", "010-0000-0000"),
        OrderLine("ORD-2", "사과", "감홍사과", 1, 59000, "S2", "이서연", "성남시", "010-1111-1111"),
    ]
    client = MockCommerceClient(orders)
    tracking_map = {"ORD-1": "TRACK123"}

    dispatched, missing = dispatch_orders(orders, tracking_map, client)

    assert [o.order_id for o in dispatched] == ["ORD-1"]
    assert dispatched[0].status == OrderStatus.SHIPPED
    assert dispatched[0].tracking_number == "TRACK123"
    assert missing == ["ORD-2"]

    summary = shipping_status_summary(orders)
    assert summary[OrderStatus.SHIPPED.value] == 1
    assert summary[OrderStatus.NEW.value] == 1


def test_dispatch_orders_is_idempotent_for_already_shipped_orders():
    """송장 CSV가 누적/재업로드되는 상황을 시뮬레이션한다: 이미 발송 처리된
    주문이 다시 들어와도 재처리(발송 API 재호출)되면 안 된다."""
    orders = [
        OrderLine("ORD-1", "고구마", "베니하르카 호박고구마", 2, 32000, "S1", "김민준", "서울시", "010-0000-0000"),
        OrderLine("ORD-2", "사과", "감홍사과", 1, 59000, "S2", "이서연", "성남시", "010-1111-1111"),
    ]
    client = MockCommerceClient(orders)

    # 1차 실행: ORD-1 발송 처리
    dispatched_1, _ = dispatch_orders(orders, {"ORD-1": "TRACK123"}, client)
    assert [o.order_id for o in dispatched_1] == ["ORD-1"]

    # 2차 실행: 누적 CSV에 ORD-1이 다른 송장번호로 다시 포함되어 들어옴
    dispatched_2, missing_2 = dispatch_orders(
        orders, {"ORD-1": "TRACK999", "ORD-2": "TRACK456"}, client
    )

    # 이미 발송된 ORD-1은 재처리 대상도, 미수집 대상도 아니어야 한다.
    assert [o.order_id for o in dispatched_2] == ["ORD-2"]
    assert missing_2 == []
    # 기존 송장번호가 새 값으로 덮어써지지 않아야 한다.
    order_1 = next(o for o in orders if o.order_id == "ORD-1")
    assert order_1.tracking_number == "TRACK123"
