import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from flying_geese.live_pipeline import (
    LiveConfig,
    _compute_trend_ratios,
    _load_kamis_item_map,
    _normalize_to_category,
    run_live_pipeline,
)
from flying_geese.models import OrderLine, PriceRecord
from flying_geese.stage2_blue_ocean.naver_searchad import NaverSearchAdClient as RealNaverSearchAdClient


def test_load_kamis_item_map_raises_clear_error_when_file_missing(tmp_path):
    missing = tmp_path / "kamis_item_map.json"
    with pytest.raises(FileNotFoundError, match="kamis_item_map.example.json"):
        _load_kamis_item_map(missing)


def test_load_kamis_item_map_rejects_unfilled_todo_placeholders(tmp_path):
    path = tmp_path / "kamis_item_map.json"
    path.write_text(
        json.dumps({"사과": {"item_code": "TODO_KAMIS_ITEM_CODE", "kind_code": "06", "category_code": "400"}}),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="item_code가 아직 채워지지 않았습니다"):
        _load_kamis_item_map(path)


def test_load_kamis_item_map_accepts_filled_values(tmp_path):
    path = tmp_path / "kamis_item_map.json"
    path.write_text(
        json.dumps({"사과": {"item_code": "411", "kind_code": "06", "category_code": "400"}}),
        encoding="utf-8",
    )
    item_map = _load_kamis_item_map(path)
    assert item_map["사과"]["item_code"] == "411"


def test_normalize_to_category_overwrites_source_specific_codes():
    """KAMIS와 KAFB2B가 같은 대표품목에 서로 다른 코드를 매겨도, 정규화 후에는
    가격 변동성 판정이 같은 품목으로 묶이도록 product_code까지 통일돼야 한다."""
    records = [
        PriceRecord("411-KAMIS", "사과(홍로)", "가락", date(2026, 8, 20), 3800),
        PriceRecord("APL-KAFB2B", "사과 홍로", "안동", date(2026, 8, 19), 3750),
    ]
    normalized = _normalize_to_category(records, "사과")
    assert all(r.product_code == "사과" for r in normalized)
    assert all(r.product_name == "사과" for r in normalized)


def test_compute_trend_ratios_skips_keywords_with_no_baseline_data():
    recent = {"감홍사과": 60.0, "신규품종": 10.0}
    baseline = {"감홍사과": 40.0}  # 신규품종은 기준 구간 데이터 없음
    trends = _compute_trend_ratios(recent, baseline)
    assert trends == {"감홍사과": 1.5}
    assert "신규품종" not in trends


def test_run_live_pipeline_fails_fast_without_kamis_credentials(monkeypatch):
    monkeypatch.delenv("KAMIS_CERT_KEY", raising=False)
    monkeypatch.delenv("KAMIS_CERT_ID", raising=False)
    with pytest.raises(RuntimeError, match="KAMIS_CERT_KEY"):
        run_live_pipeline()


def test_run_live_pipeline_fails_fast_without_searchad_credentials(monkeypatch):
    monkeypatch.setenv("KAMIS_CERT_KEY", "dummy")
    monkeypatch.setenv("KAMIS_CERT_ID", "dummy")
    monkeypatch.delenv("NAVER_SEARCHAD_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="NAVER_SEARCHAD"):
        run_live_pipeline()


def test_run_live_pipeline_orchestration_with_mocked_clients(monkeypatch, tmp_path):
    """네트워크 호출 없이, 각 실 API 클라이언트를 모킹해 오케스트레이션(호출
    순서/데이터 결합)이 올바른지 검증한다. 실제 API 응답 형식 자체는 이
    테스트로 검증되지 않는다 - 그건 실 키로 직접 확인해야 한다."""
    monkeypatch.setenv("KAMIS_CERT_KEY", "dummy")
    monkeypatch.setenv("KAMIS_CERT_ID", "dummy")
    monkeypatch.setenv("NAVER_SEARCHAD_API_KEY", "dummy")
    monkeypatch.setenv("NAVER_SEARCHAD_SECRET_KEY", "dummy")
    monkeypatch.setenv("NAVER_SEARCHAD_CUSTOMER_ID", "dummy")
    monkeypatch.setenv("COMMERCE_API_BASE_URL", "https://example.com")
    monkeypatch.setenv("COMMERCE_API_KEY", "dummy")

    kamis_item_map = tmp_path / "kamis_item_map.json"
    kamis_item_map.write_text(
        json.dumps({"고구마": {"item_code": "152", "kind_code": "01", "category_code": "200"}}),
        encoding="utf-8",
    )
    variety_map = tmp_path / "variety_map.json"
    variety_map.write_text(json.dumps({"고구마": ["베니하르카 호박고구마"]}), encoding="utf-8")
    seasonal_calendar = tmp_path / "seasonal_calendar.json"
    seasonal_calendar.write_text(
        json.dumps([{"category": "고구마", "variety": "베니하르카 호박고구마", "type": "농산", "peak_months": list(range(1, 13))}]),
        encoding="utf-8",
    )
    suppliers_path = tmp_path / "suppliers.json"
    suppliers_path.write_text(json.dumps([]), encoding="utf-8")
    tracking_csv = tmp_path / "tracking.csv"
    tracking_csv.write_text("order_id,tracking_number\n", encoding="utf-8")

    config = LiveConfig(
        kamis_item_map_path=kamis_item_map,
        seasonal_calendar_path=seasonal_calendar,
        variety_map_path=variety_map,
        apc_sites_path=tmp_path / "apc_sites_missing.json",
        competitor_counts_path=tmp_path / "competitor_counts_missing.json",
        suppliers_path=suppliers_path,
        tracking_csv_path=tracking_csv,
        output_dir=tmp_path,
    )

    fake_price_record = PriceRecord("152", "고구마", "가락", date(2026, 8, 20), 4200)
    fake_order = OrderLine(
        "ORD-1", "고구마", "베니하르카 호박고구마", 2, 32000, "S1", "김민준", "서울시", "010-0000-0000"
    )

    with (
        patch("flying_geese.live_pipeline.KamisClient") as MockKamis,
        patch("flying_geese.live_pipeline.NaverSearchAdClient") as MockSearchAd,
        patch("flying_geese.live_pipeline.RestCommerceClient") as MockCommerce,
    ):
        MockKamis.return_value.fetch_period_prices.return_value = [fake_price_record]
        MockSearchAd.return_value.keyword_stats.return_value = [
            {"relKeyword": "베니하르카 호박고구마", "monthlyPcQcCnt": "3000", "monthlyMobileQcCnt": "1200"}
        ]
        # monthly_search_volume은 @staticmethod라 클래스 전체를 모킹하면 같이
        # 가려진다 - 실제 계산 로직을 그대로 위임하도록 복원한다.
        MockSearchAd.monthly_search_volume = staticmethod(RealNaverSearchAdClient.monthly_search_volume)
        MockCommerce.return_value.fetch_new_orders.return_value = [fake_order]

        report = run_live_pipeline(config=config, target_month=8)

    assert report.passing_price_items[0].product_name == "고구마"
    assert report.blue_ocean_ranking[0].variety_keyword == "베니하르카 호박고구마"
    assert report.blue_ocean_ranking[0].monthly_search_volume == 4200
    assert report.apc_priority_products == set()  # APC 파일 없음 -> 빈 값으로 안전하게 진행
    assert report.purchase_order_path.exists()
