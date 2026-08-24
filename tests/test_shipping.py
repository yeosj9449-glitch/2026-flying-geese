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
