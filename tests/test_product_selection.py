import json

import pytest

from flying_geese.product_selection import run_product_selection


def _write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_run_product_selection_raises_clear_error_without_price_records(tmp_path):
    with pytest.raises(FileNotFoundError, match="price_records"):
        run_product_selection(data_dir=tmp_path)


def test_run_product_selection_works_with_only_price_records(tmp_path):
    """search_volumes/competitor_counts/search_trends/apc_sites가 전부 없어도
    (경쟁상품 데이터 등을 아직 조사하지 못한 첫 실행) 죽지 않고 안전하게 동작해야 한다."""
    _write_json(
        tmp_path / "price_records.json",
        [
            {"product_code": "사과", "product_name": "사과", "market": "가락", "trade_date": "2025-08-20", "price_per_unit": 3500},
            {"product_code": "사과", "product_name": "사과", "market": "가락", "trade_date": "2026-07-21", "price_per_unit": 3700},
            {"product_code": "사과", "product_name": "사과", "market": "가락", "trade_date": "2026-08-20", "price_per_unit": 3800},
        ],
    )

    report = run_product_selection(data_dir=tmp_path, target_month=8)

    assert report.passing_price_items[0].product_name == "사과"
    assert report.apc_priority_products == set()
    # 검색량 데이터가 없으므로 블루오션 후보는 비어있어야 한다(크래시 없이).
    assert report.blue_ocean_ranking == []


def test_run_product_selection_excludes_price_surge_and_scores_with_manual_search_data(tmp_path):
    _write_json(
        tmp_path / "price_records.json",
        [
            {"product_code": "사과", "product_name": "사과", "market": "가락", "trade_date": "2025-08-20", "price_per_unit": 3500},
            {"product_code": "사과", "product_name": "사과", "market": "가락", "trade_date": "2026-07-21", "price_per_unit": 3700},
            {"product_code": "사과", "product_name": "사과", "market": "가락", "trade_date": "2026-08-20", "price_per_unit": 3800},
            {"product_code": "배추", "product_name": "배추", "market": "가락", "trade_date": "2025-08-20", "price_per_unit": 2000},
            {"product_code": "배추", "product_name": "배추", "market": "가락", "trade_date": "2026-07-21", "price_per_unit": 2600},
            {"product_code": "배추", "product_name": "배추", "market": "가락", "trade_date": "2026-08-20", "price_per_unit": 2800},
        ],
    )
    _write_json(tmp_path / "search_volumes.json", {"홍로사과": 6000})
    _write_json(tmp_path / "competitor_counts.json", {"홍로사과": 300})

    report = run_product_selection(data_dir=tmp_path, target_month=8)

    product_names = {r.product_name for r in report.passing_price_items}
    assert "사과" in product_names
    assert "배추" not in product_names  # YoY 40% 폭등으로 제외

    assert len(report.blue_ocean_ranking) == 1
    assert report.blue_ocean_ranking[0].variety_keyword == "홍로사과"
