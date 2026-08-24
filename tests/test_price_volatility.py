from datetime import date

from flying_geese.models import PriceRecord
from flying_geese.stage1_calendar.price_volatility import evaluate_volatility, filter_passing


def test_excludes_yoy_price_surge():
    records = [
        PriceRecord("P001", "배추", "가락", date(2025, 8, 20), 2000),
        PriceRecord("P001", "배추", "가락", date(2026, 7, 21), 2600),
        PriceRecord("P001", "배추", "가락", date(2026, 8, 20), 2800),
    ]
    results = evaluate_volatility(records, surge_exclude_pct=20.0)
    assert len(results) == 1
    assert results[0].excluded is True
    assert "전년" in results[0].exclude_reason


def test_passes_stable_price():
    records = [
        PriceRecord("P002", "사과", "가락", date(2025, 8, 20), 3500),
        PriceRecord("P002", "사과", "가락", date(2026, 7, 21), 3700),
        PriceRecord("P002", "사과", "가락", date(2026, 8, 20), 3800),
    ]
    results = evaluate_volatility(records, surge_exclude_pct=20.0)
    passing = filter_passing(results)
    assert len(passing) == 1
    assert passing[0].excluded is False


def test_no_reference_price_yields_none_changes():
    records = [PriceRecord("P003", "고구마", "가락", date(2026, 8, 20), 4200)]
    results = evaluate_volatility(records)
    assert results[0].mom_change_pct is None
    assert results[0].yoy_change_pct is None
    assert results[0].excluded is False
