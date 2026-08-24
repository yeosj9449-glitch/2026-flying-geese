from flying_geese.models import OrderStatus
from flying_geese.stage5_automation.commerce_api import _parse_orders


def test_parse_orders_normal_rows():
    rows = [
        {
            "orderId": "ORD-1",
            "productName": "고구마",
            "varietyKeyword": "베니하르카 호박고구마",
            "quantity": 2,
            "unitPrice": 32000,
            "supplierId": "S1",
            "buyerName": "김민준",
            "buyerAddress": "서울시",
            "buyerPhone": "010-0000-0000",
        }
    ]
    orders = _parse_orders(rows)
    assert len(orders) == 1
    assert orders[0].order_id == "ORD-1"
    assert orders[0].status == OrderStatus.NEW


def test_parse_orders_skips_malformed_row_without_failing_the_batch():
    """주문 하나가 필수 필드 누락/null이어도 나머지 정상 주문은 그대로
    반환돼야 한다 - 하루치 전체 주문이 이 한 건 때문에 통째로 막히면 안 된다."""
    rows = [
        {  # quantity가 null인 malformed 주문
            "orderId": "ORD-BAD",
            "productName": "사과",
            "quantity": None,
            "unitPrice": 59000,
        },
        {
            "orderId": "ORD-GOOD",
            "productName": "고구마",
            "quantity": 3,
            "unitPrice": 32000,
        },
    ]
    orders = _parse_orders(rows)
    assert [o.order_id for o in orders] == ["ORD-GOOD"]


def test_parse_orders_falls_back_variety_keyword_to_product_name_when_null():
    rows = [
        {
            "orderId": "ORD-1",
            "productName": "사과",
            "varietyKeyword": None,
            "quantity": 1,
            "unitPrice": 59000,
        }
    ]
    orders = _parse_orders(rows)
    assert orders[0].variety_keyword == "사과"


def test_parse_orders_skips_row_missing_required_key():
    rows = [{"productName": "품목만있음"}]  # orderId 등 누락
    orders = _parse_orders(rows)
    assert orders == []
