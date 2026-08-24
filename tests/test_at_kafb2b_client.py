from datetime import date

from flying_geese.stage1_calendar.at_kafb2b_client import AtKafb2bClient


def test_parse_rows_normal_row():
    rows = [
        {
            "itemCode": "225",
            "itemName": "감홍사과",
            "marketName": "가락도매시장",
            "tradeDate": "2026-08-20",
            "price": "3,800",
        }
    ]
    records = AtKafb2bClient._parse_rows(rows)
    assert len(records) == 1
    assert records[0].product_code == "225"
    assert records[0].product_name == "감홍사과"
    assert records[0].market == "가락도매시장"
    assert records[0].trade_date == date(2026, 8, 20)
    assert records[0].price_per_unit == 3800.0


def test_parse_rows_skips_malformed_row_without_failing_the_batch():
    rows = [
        {"itemCode": None, "itemName": None, "marketName": None, "tradeDate": "잘못된날짜", "price": "1,000"},
        {"itemCode": "230", "itemName": "배추", "tradeDate": "2026-08-21", "price": "2,000"},
    ]
    records = AtKafb2bClient._parse_rows(rows)
    assert len(records) == 1
    assert records[0].product_name == "배추"


def test_parse_rows_falls_back_market_to_national_when_null():
    rows = [{"itemCode": "1", "itemName": "정상", "marketName": None, "tradeDate": "2026-08-20", "price": "1,000"}]
    records = AtKafb2bClient._parse_rows(rows)
    assert records[0].market == "전국"


def test_parse_rows_skips_row_missing_required_key():
    rows = [{"itemName": "품목만있음"}]  # tradeDate 등 누락
    records = AtKafb2bClient._parse_rows(rows)
    assert records == []
