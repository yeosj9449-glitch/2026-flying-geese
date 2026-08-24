"""실 API 연동 파이프라인.

`pipeline.py`(데모, `data/sample/` 로컬 데이터 기반)와 달리, 설정된 API 키로
KAMIS/aT KAFB2B/네이버 데이터랩·검색광고/커머스 API를 실제로 호출한다.
가격 변동성 판정, 블루오션 스코어링, 공급처 리스크 필터, 마진 시뮬레이터,
발송 처리 로직은 데모 파이프라인과 완전히 동일한 순수 함수를 재사용한다 -
데이터를 어디서 가져오는지만 다르다. 결과는 데모와 동일한 `PipelineReport`
형태로 반환된다.

경쟁상품 수(쿠팡/스마트스토어)와 공급처 신뢰도는 공식 실시간 API가 없는
영역이라, 데모와 마찬가지로 운영자가 관리하는 로컬 JSON을 계속 사용한다
(`data/live/` 아래, `.example.json`을 복사해 채워 넣는 방식).

⚠ 중요: 이 모듈은 실제 네트워크 호출을 전제로 하며, 이 저장소의 자동화
테스트 환경(오프라인 샌드박스)에서는 실 API에 대한 종단간(End-to-End) 호출을
검증하지 못했다. `data/live/kamis_item_map.example.json`의 품목/품종 코드는
반드시 KAMIS 표준코드 조회 API(또는 공식 문서)로 실제 값을 확인한 뒤 채워야
하며, 운영 투입 전 실 API 키로 직접 검증이 필요하다.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from flying_geese.config import Settings, load_settings
from flying_geese.models import PriceRecord
from flying_geese.pipeline import DEFAULT_DATA_DIR, PipelineReport
from flying_geese.stage1_calendar.apc_connector import load_apc_sites, products_with_apc_priority
from flying_geese.stage1_calendar.at_kafb2b_client import AtKafb2bClient
from flying_geese.stage1_calendar.kamis_client import KamisClient
from flying_geese.stage1_calendar.price_volatility import evaluate_volatility, filter_passing
from flying_geese.stage1_calendar.seasonal_calendar import (
    category_variety_map,
    items_for_month,
    load_seasonal_calendar,
    upcoming_items,
)
from flying_geese.stage2_blue_ocean.marketplace_rank import (
    StaticMarketplaceRankSource,
    bulk_competitor_counts,
)
from flying_geese.stage2_blue_ocean.naver_datalab import NaverDatalabClient
from flying_geese.stage2_blue_ocean.naver_searchad import NaverSearchAdClient
from flying_geese.stage2_blue_ocean.scoring import build_candidates, rank_blue_ocean
from flying_geese.stage2_blue_ocean.variety_extractor import expand_varieties, load_variety_map
from flying_geese.stage3_supplier.risk_filter import evaluate_suppliers
from flying_geese.stage3_supplier.supplier_metrics import load_suppliers
from flying_geese.stage4_simulator.cashflow import project_cashflow
from flying_geese.stage4_simulator.margin_simulator import simulate
from flying_geese.stage5_automation.commerce_api import RestCommerceClient
from flying_geese.stage5_automation.purchase_order import generate_purchase_order_excel
from flying_geese.stage5_automation.shipping import (
    dispatch_orders,
    load_tracking_numbers_from_csv,
    shipping_status_summary,
)

logger = logging.getLogger(__name__)

LIVE_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "live"
_TODO_MARKER = "TODO"


@dataclass
class LiveConfig:
    """실전 파이프라인의 로컬 데이터 소스 경로 모음 (모두 운영자가 채워야 함)."""

    kamis_item_map_path: Path = field(default_factory=lambda: LIVE_DATA_DIR / "kamis_item_map.json")
    # 제철 캘린더/품종 매핑은 데모용으로 지어낸 가짜 데이터가 아니라 실제 농산물
    # 품종/제철 지식으로 작성한 참고 데이터라 실전에서도 그대로 재사용한다.
    # (운영자가 취급 품목 범위에 맞게 계속 보강하는 것을 권장한다.)
    seasonal_calendar_path: Path = field(default_factory=lambda: DEFAULT_DATA_DIR / "seasonal_calendar.json")
    variety_map_path: Path = field(default_factory=lambda: DEFAULT_DATA_DIR / "variety_map.json")
    # 아래는 반대로, data/sample의 값 자체가 데모용으로 지어낸 예시라 실전에서
    # 절대 그대로 쓰면 안 되는 것들이다 - data/live/*.example.json을 복사해
    # 운영자가 실제로 조사/계약한 값으로 채워야 한다.
    apc_sites_path: Path = field(default_factory=lambda: LIVE_DATA_DIR / "apc_sites.json")
    competitor_counts_path: Path = field(default_factory=lambda: LIVE_DATA_DIR / "competitor_counts.json")
    suppliers_path: Path = field(default_factory=lambda: LIVE_DATA_DIR / "suppliers.json")
    tracking_csv_path: Path = field(default_factory=lambda: LIVE_DATA_DIR / "tracking.csv")
    output_dir: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent / "output")
    price_history_days: int = 400  # 최신가 대비 전년(365일) 비교에 여유를 둔 조회 기간


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_kamis_item_map(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(
            f"KAMIS 품목코드 맵 파일을 찾을 수 없습니다: {path}. "
            "data/live/kamis_item_map.example.json을 복사해 실제 KAMIS 표준코드로 채워주세요."
        )
    item_map = _load_json(path)
    for category, codes in item_map.items():
        for required_field in ("item_code", "kind_code", "category_code"):
            value = codes.get(required_field, "")
            if not value or str(value).startswith(_TODO_MARKER):
                raise RuntimeError(
                    f"'{category}'의 KAMIS {required_field}가 아직 채워지지 않았습니다 ({path}). "
                    "KAMIS 표준코드 조회 API 또는 공식 문서에서 실제 값을 확인해 채워주세요."
                )
    return item_map


def _normalize_to_category(records: list[PriceRecord], category: str) -> list[PriceRecord]:
    """서로 다른 소스(KAMIS/KAFB2B)가 같은 대표품목에 다른 코드를 매길 수 있어,
    가격 변동성 판정이 소스와 무관하게 같은 품목으로 묶이도록 정규화한다."""
    for record in records:
        record.product_code = category
        record.product_name = category
    return records


def _fetch_live_prices(
    settings: Settings, item_map: dict[str, dict[str, str]], history_days: int
) -> list[PriceRecord]:
    end_day = date.today()
    start_day = end_day - timedelta(days=history_days)

    records: list[PriceRecord] = []
    kamis = KamisClient(settings)
    for category, codes in item_map.items():
        fetched = kamis.fetch_period_prices(
            item_code=codes["item_code"],
            kind_code=codes["kind_code"],
            start_day=start_day,
            end_day=end_day,
            category_code=codes.get("category_code", "200"),
        )
        records.extend(_normalize_to_category(fetched, category))

    if settings.at_kafb2b_ready():
        kafb2b = AtKafb2bClient(settings)
        for category, codes in item_map.items():
            try:
                fetched = kafb2b.fetch_period_prices(
                    item_code=codes["item_code"], start_day=start_day, end_day=end_day
                )
            except Exception:
                logger.warning("KAFB2B 조회 실패, 이 소스는 건너뜁니다 (품목: %s)", category, exc_info=True)
                continue
            records.extend(_normalize_to_category(fetched, category))
    else:
        logger.info("AT_KAFB2B_API_KEY/AT_KAFB2B_BASE_URL 미설정 - KAFB2B 조회를 건너뛰고 KAMIS만 사용합니다.")

    return records


def _compute_trend_ratios(
    recent_ratio: dict[str, float], baseline_ratio: dict[str, float]
) -> dict[str, float]:
    """최근 구간 검색 비율 / 기준 구간 검색 비율로 모멘텀을 계산한다.
    기준 구간에 데이터가 없는(0) 키워드는 계산하지 않는다(호출부에서 기본값 1.0 처리)."""
    trends: dict[str, float] = {}
    for keyword, recent in recent_ratio.items():
        baseline = baseline_ratio.get(keyword, 0.0)
        if baseline > 0:
            trends[keyword] = recent / baseline
    return trends


def _fetch_live_search_data(
    settings: Settings, varieties: list[str], competitor_counts: dict[str, int]
) -> tuple[dict[str, int], dict[str, float]]:
    """검색량(검색광고)과 검색 모멘텀(데이터랩)을 조회한다.

    ⚠ 네이버 검색광고 API의 hintKeywords는 원래 공백 없는 시드 키워드를
    전제로 설계됐다 - "베니하르카 호박고구마"처럼 공백이 포함된 세부 품종
    키워드는 실제 응답이 기대와 다를 수 있으니 운영 투입 전 직접 확인한다.
    """
    search_volumes: dict[str, int] = {}
    if varieties:
        searchad = NaverSearchAdClient(settings)
        for row in searchad.keyword_stats(varieties):
            keyword = row.get("relKeyword", "")
            if keyword in varieties:
                search_volumes[keyword] = NaverSearchAdClient.monthly_search_volume(row)

    search_trends: dict[str, float] = {}
    if varieties and settings.naver_datalab_ready():
        datalab = NaverDatalabClient(settings)
        end_day = date.today()
        recent_start = end_day - timedelta(days=30)
        baseline_start = end_day - timedelta(days=90)
        recent = NaverDatalabClient.latest_ratio_by_keyword(
            datalab.search_trend(varieties, recent_start, end_day)
        )
        baseline = NaverDatalabClient.latest_ratio_by_keyword(
            datalab.search_trend(varieties, baseline_start, recent_start)
        )
        search_trends = _compute_trend_ratios(recent, baseline)

    return search_volumes, search_trends


def run_live_pipeline(
    config: LiveConfig | None = None, target_month: int | None = None
) -> PipelineReport:
    settings = load_settings()
    config = config or LiveConfig()
    target_month = target_month or date.today().month

    if not settings.kamis_ready():
        raise RuntimeError(
            "KAMIS_CERT_KEY/KAMIS_CERT_ID가 설정되지 않았습니다. "
            "실전 파이프라인은 최소 KAMIS 연동이 필요합니다."
        )
    if not settings.naver_searchad_ready():
        raise RuntimeError(
            "NAVER_SEARCHAD_API_KEY/SECRET_KEY/CUSTOMER_ID가 설정되지 않았습니다. "
            "블루오션 스코어링에는 검색량 데이터가 필수입니다."
        )

    # --- 1단계: 실 가격 이력 조회 + 제철 캘린더 매칭 (데모와 동일한 순수 로직 재사용) ---
    item_map = _load_kamis_item_map(config.kamis_item_map_path)
    records = _fetch_live_prices(settings, item_map, config.price_history_days)
    volatility_results = evaluate_volatility(records, settings.price_surge_exclude_pct)
    passing_prices = filter_passing(volatility_results)
    passing_categories = sorted({r.product_name for r in passing_prices})

    if config.apc_sites_path.exists():
        apc_sites = load_apc_sites(config.apc_sites_path)
        apc_products = products_with_apc_priority(apc_sites)
    else:
        # APC 우선 연동은 정보성 가점일 뿐 하드 게이트가 아니므로, 데이터가
        # 없으면(아직 조사 전이면) 빈 값으로 진행한다 - data/sample의 예시
        # APC 데이터를 실전에서 대신 쓰면 안 되므로 그쪽으로 폴백하지 않는다.
        logger.info("APC 데이터 파일이 없습니다 (%s) - 우선 연동 표시 없이 진행합니다.", config.apc_sites_path)
        apc_products = set()

    calendar_items = load_seasonal_calendar(config.seasonal_calendar_path)
    this_month_map = category_variety_map(items_for_month(calendar_items, target_month))
    seasonal_variety_map = {
        category: varieties
        for category, varieties in this_month_map.items()
        if category in passing_categories
    }
    upcoming = upcoming_items(calendar_items, target_month, lookahead_months=1)

    # --- 2단계: 실 검색량/모멘텀 조회 + 블루오션 스코어링 ---
    variety_map = load_variety_map(config.variety_map_path)
    fallback_categories = [c for c in passing_categories if c not in seasonal_variety_map]
    fallback_map = expand_varieties(fallback_categories, variety_map)
    combined_map = {**fallback_map, **seasonal_variety_map}

    all_varieties = sorted({v for varieties in combined_map.values() for v in varieties})
    if config.competitor_counts_path.exists():
        competitor_raw = _load_json(config.competitor_counts_path)
    else:
        # StaticMarketplaceRankSource의 default_count(999)가 이미 "모르면 경쟁
        # 심하다고 가정"하는 보수적인 값이라, 파일이 없어도 안전하게 진행한다.
        logger.info(
            "경쟁상품 데이터 파일이 없습니다 (%s) - 미등록 품종은 경쟁 심함으로 가정합니다.",
            config.competitor_counts_path,
        )
        competitor_raw = {}
    competitor_source = StaticMarketplaceRankSource(competitor_raw)
    competitor_counts = bulk_competitor_counts(competitor_source, all_varieties)
    search_volumes, search_trends = _fetch_live_search_data(settings, all_varieties, competitor_counts)

    all_candidates = []
    all_missing: list[str] = []
    for base_product, varieties in combined_map.items():
        candidates, missing = build_candidates(
            base_product, varieties, search_volumes, competitor_counts, search_trends
        )
        all_candidates.extend(candidates)
        all_missing.extend(missing)
    blue_ocean_ranking = rank_blue_ocean(
        all_candidates, min_search_volume=settings.min_blue_ocean_search_volume
    )

    # --- 3단계: 공급처 신뢰도 (운영자 관리 데이터, 데모와 동일 로직) ---
    suppliers = load_suppliers(config.suppliers_path)
    supplier_evaluations = evaluate_suppliers(suppliers, settings)

    # --- 4단계: 마진 & 목표 역산 시뮬레이터 (API 불필요, 데모와 동일) ---
    simulation = simulate(
        settings.target_monthly_revenue, platform_commission_rate=settings.platform_commission_rate
    )
    cashflow = project_cashflow(settings.target_monthly_revenue)

    # --- 5단계: 실 커머스 API로 주문 수집 + 발주서 생성 + 발송 처리 ---
    commerce_client = RestCommerceClient(settings)
    new_orders = commerce_client.fetch_new_orders()
    po_path = generate_purchase_order_excel(new_orders, config.output_dir / "purchase_order.xlsx")
    tracking_map = load_tracking_numbers_from_csv(config.tracking_csv_path)
    dispatched, missing_tracking = dispatch_orders(new_orders, tracking_map, commerce_client)
    shipping_summary = shipping_status_summary(new_orders)

    return PipelineReport(
        target_month=target_month,
        passing_price_items=passing_prices,
        apc_priority_products=apc_products,
        seasonal_matched_categories=set(seasonal_variety_map.keys()),
        upcoming_next_month=upcoming,
        blue_ocean_ranking=blue_ocean_ranking,
        blue_ocean_missing_competitor_data=all_missing,
        supplier_evaluations=supplier_evaluations,
        simulation=simulation,
        cashflow=cashflow,
        purchase_order_path=po_path,
        dispatched_orders=dispatched,
        missing_tracking_order_ids=missing_tracking,
        shipping_summary=shipping_summary,
    )
