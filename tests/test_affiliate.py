import hashlib
import hmac
from datetime import date

import pytest

from flying_geese.affiliate.content_builder import DISCLOSURE, build_post_draft, write_drafts
from flying_geese.affiliate.coupang_partners_api import (
    AffiliateProduct,
    DailyCommission,
    parse_commission_report,
    parse_deeplinks,
    parse_search_products,
    sign,
)
from flying_geese.affiliate.goal_calculator import (
    FunnelAssumptions,
    plan_for_target,
    project_commission,
)
from flying_geese.affiliate.performance import progress_report
from flying_geese.affiliate.pipeline import run_affiliate_drafts

FUNNEL = FunnelAssumptions("테스트", avg_order_value=40_000, click_to_order_rate=0.05,
                           view_to_click_rate=0.04, views_per_post_per_day=15)
PRODUCT = AffiliateProduct("1", "홍로사과 5kg", 29_900, "https://link.coupang.com/a/abc", is_rocket=True)


def test_plan_for_target_reverse_calculates_funnel():
    plan = plan_for_target(1_000_000, 0.03, FUNNEL, days=30)
    assert plan.required_sales == 33_333_334
    assert plan.required_orders == 834
    assert plan.required_clicks == 16_680
    assert plan.required_views == 417_000
    assert plan.required_posts == 1_854  # 417,000 / (15 * 15일)
    assert not plan.feasible


def test_plan_for_target_rejects_zero_rate():
    with pytest.raises(ValueError):
        plan_for_target(1_000_000, 0, FUNNEL)


def test_project_commission_is_consistent_with_plan():
    plan = plan_for_target(1_000_000, 0.03, FUNNEL, days=30)
    assert project_commission(plan.required_posts / 30, 0.03, FUNNEL) >= 1_000_000


def test_sign_matches_hmac_of_concatenated_message():
    expected = hmac.new(b"secret", b"260101T000000ZGET/v1/xkeyword=a", hashlib.sha256).hexdigest()
    assert sign("secret", "260101T000000Z", "GET", "/v1/x", "keyword=a") == expected


def test_parse_search_products_skips_malformed_rows():
    payload = {"rCode": "0", "data": {"productData": [
        {"productId": 1, "productName": "홍로사과 5kg", "productPrice": 29900,
         "productUrl": "https://link.coupang.com/a/abc", "isRocket": True},
        {"productId": 2, "productName": None, "productUrl": "https://x"},
        {"productId": 3, "productName": "가격없음", "productPrice": None, "productUrl": "https://y"},
    ]}}
    products = parse_search_products(payload, "홍로사과")
    assert [p.product_id for p in products] == ["1", "3"]
    assert products[0].is_rocket and products[0].keyword == "홍로사과"
    assert products[1].product_price == 0


def test_parse_search_products_handles_null_data():
    assert parse_search_products({"rCode": "0", "data": None}) == []


def test_parse_deeplinks_and_commission_report():
    links = parse_deeplinks({"data": [{"originalUrl": "a", "shortenUrl": "s"}, {"originalUrl": "b"}]})
    assert links == {"a": "s"}
    rows = parse_commission_report({"data": [
        {"date": "20261001", "commission": "1200", "click": 30, "order": None},
        {"date": None, "commission": 999},
    ]})
    assert rows == [DailyCommission("20261001", 1200, clicks=30, orders=0)]


def test_post_draft_has_disclosure_at_top_and_bottom():
    draft = build_post_draft("홍로사과", [PRODUCT], today=date(2026, 10, 17))
    lines = draft.splitlines()
    assert lines[0] == f"> {DISCLOSURE}"
    assert draft.rstrip().endswith(DISCLOSURE)
    assert "https://link.coupang.com/a/abc" in draft
    assert "29,900원" in draft


def test_post_draft_refuses_empty_disclosure_or_products():
    with pytest.raises(ValueError):
        build_post_draft("홍로사과", [PRODUCT], disclosure=" ")
    with pytest.raises(ValueError):
        build_post_draft("홍로사과", [])


def test_write_drafts_slugifies_filename(tmp_path):
    paths = write_drafts({"홍로 사과/5kg": "body"}, tmp_path, today=date(2026, 10, 17))
    assert paths[0].name == "2026-10-17_홍로-사과-5kg.md"


class _FakeClient:
    def search_products(self, keyword, limit=5):
        if keyword == "에러":
            raise RuntimeError("rate limit")
        return [] if keyword == "없음" else [PRODUCT]


def test_run_affiliate_drafts_isolates_keyword_failures(tmp_path):
    report = run_affiliate_drafts(["홍로사과", "에러", "없음", "홍로사과"], _FakeClient(), output_dir=tmp_path)
    assert len(report.draft_paths) == 1
    assert report.empty_keywords == ["없음"]
    assert "에러" in report.failed_keywords


def test_progress_report_projects_month_end():
    rows = [
        DailyCommission("20261001", 10_000, clicks=100, orders=5),
        DailyCommission("20261010", 20_000, clicks=100, orders=5),
        DailyCommission("20260930", 99_999),  # 지난달은 제외
    ]
    report = progress_report(rows, 1_000_000, date(2026, 10, 10))
    assert report.earned_to_date == 30_000
    assert report.daily_run_rate == 3_000
    assert report.projected_month_end == 93_000
    assert report.required_daily_for_target == 970_000 // 21
    assert report.observed_click_to_order_rate == pytest.approx(0.05)
    assert not report.on_track
