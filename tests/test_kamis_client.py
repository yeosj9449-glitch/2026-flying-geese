from datetime import date

from flying_geese.stage1_calendar.kamis_client import KamisClient, _parse_kamis_date


def test_parse_handles_normal_row():
    payload = {
        "data": {
            "item": [
                {
                    "itemcode": "225",
                    "itemname": "사과",
                    "countyname": "서울",
                    "yyyy": "2026",
                    "regday": "08/20",
                    "price": "3,800",
                }
            ]
        }
    }
    records = KamisClient._parse(payload)
    assert len(records) == 1
    assert records[0].product_code == "225"
    assert records[0].product_name == "사과"
    assert records[0].market == "서울"
    assert records[0].trade_date == date(2026, 8, 20)
    assert records[0].price_per_unit == 3800.0


def test_parse_does_not_crash_on_explicit_json_null_fields():
    """KAMIS가 일부 필드를 JSON null로 내려줘도(키는 존재) 파싱 전체가
    죽지 않고, 해당 필드만 안전한 기본값으로 대체돼야 한다."""
    payload = {
        "data": {
            "item": [
                {
                    "itemcode": None,
                    "itemname": None,
                    "countyname": None,
                    "yyyy": "2026",
                    "regday": "08/20",
                    "price": "1,000",
                },
                {
                    "itemcode": "230",
                    "itemname": "배추",
                    "countyname": "부산",
                    "yyyy": "2026",
                    "regday": "08/21",
                    "price": "2,000",
                },
            ]
        }
    }
    records = KamisClient._parse(payload)
    assert len(records) == 2
    assert records[0].product_code == ""
    assert records[0].product_name == ""
    assert records[0].market == "전국"
    assert records[1].product_name == "배추"


def test_parse_skips_row_with_unparseable_date_without_crashing():
    payload = {
        "data": {
            "item": [
                {"itemcode": "1", "itemname": "이상치", "yyyy": "2026", "regday": "잘못된날짜", "price": "1,000"},
                {"itemcode": "2", "itemname": "정상", "yyyy": "2026", "regday": "08/20", "price": "2,000"},
            ]
        }
    }
    records = KamisClient._parse(payload)
    assert len(records) == 1
    assert records[0].product_name == "정상"


def test_parse_skips_row_with_unparseable_price():
    payload = {
        "data": {
            "item": [
                {"itemcode": "1", "itemname": "가격없음", "yyyy": "2026", "regday": "08/20", "price": "-"},
                {"itemcode": "2", "itemname": "정상", "yyyy": "2026", "regday": "08/20", "price": "2,000"},
            ]
        }
    }
    records = KamisClient._parse(payload)
    assert len(records) == 1
    assert records[0].product_name == "정상"


def test_parse_kamis_date_valid_and_invalid():
    assert _parse_kamis_date("2026", "08/20") == date(2026, 8, 20)
    assert _parse_kamis_date(None, "08/20") is None
    assert _parse_kamis_date("2026", None) is None
    assert _parse_kamis_date("2026", "13/40") is None
