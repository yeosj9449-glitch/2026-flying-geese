"""수동 리서치 기반 상품 선정 파이프라인 (1~2단계만, API 키 불필요).

KAMIS/네이버 API 키가 아직 발급되지 않았을 때를 위한 경로다. 운영자가 KAMIS
(www.kamis.or.kr)와 네이버 검색광고/데이터랩 관리 화면에서 직접 조회한 실제
가격·검색량·경쟁상품 수 숫자를 `data/manual/`의 로컬 JSON에 채워 넣으면,
제철 검증 + 가격 변동성 필터 + 블루오션 스코어링("상품 선정", 1~2단계)까지
실행할 수 있다. 공급처/커머스 API가 필요한 3~5단계(`pipeline.py`,
`live_pipeline.py`)는 포함하지 않는다.

제철 캘린더(`seasonal_calendar.json`)와 품종 매핑(`variety_map.json`)은
데모용으로 지어낸 가짜 데이터가 아니라 실제 농산물 품종/제철 지식으로 작성한
참고 데이터라, `data/sample/`의 것을 기본값으로 그대로 재사용한다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from flying_geese.config import load_settings
from flying_geese.models import PriceRecord, SeasonalItem, VarietyCandidate, VolatilityResult
from flying_geese.pipeline import DEFAULT_DATA_DIR
from flying_geese.stage1_calendar.apc_connector import load_apc_sites, products_with_apc_priority
from flying_geese.stage1_calendar.price_volatility import evaluate_volatility, filter_passing
from flying_geese.stage1_calendar.seasonal_calendar import (
    category_variety_map,
    items_for_month,
    load_seasonal_calendar,
    upcoming_items,
)
from flying_geese.stage2_blue_ocean.scoring import build_candidates, rank_blue_ocean
from flying_geese.stage2_blue_ocean.variety_extractor import expand_varieties, load_variety_map

MANUAL_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "manual"


@dataclass
class ProductSelectionReport:
    target_month: int
    passing_price_items: list[VolatilityResult]
    apc_priority_products: set[str]
    seasonal_matched_categories: set[str]
    upcoming_next_month: list[SeasonalItem]
    blue_ocean_ranking: list[VarietyCandidate]
    blue_ocean_missing_competitor_data: list[str]


def _load_json_or(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def run_product_selection(
    data_dir: Path | None = None,
    target_month: int | None = None,
    seasonal_calendar_path: Path | None = None,
    variety_map_path: Path | None = None,
) -> ProductSelectionReport:
    settings = load_settings()
    data_dir = data_dir or MANUAL_DATA_DIR
    target_month = target_month or date.today().month
    seasonal_calendar_path = seasonal_calendar_path or (DEFAULT_DATA_DIR / "seasonal_calendar.json")
    variety_map_path = variety_map_path or (DEFAULT_DATA_DIR / "variety_map.json")

    price_records_path = data_dir / "price_records.json"
    if not price_records_path.exists():
        raise FileNotFoundError(
            f"가격 데이터 파일을 찾을 수 없습니다: {price_records_path}. "
            "KAMIS(www.kamis.or.kr)에서 직접 조회한 최근/전월/전년 가격을 "
            "data/manual/price_records.example.json 형식에 맞춰 채워주세요."
        )
    raw_records = _load_json_or(price_records_path, [])
    records = [
        PriceRecord(
            product_code=r["product_code"],
            product_name=r["product_name"],
            market=r["market"],
            trade_date=date.fromisoformat(r["trade_date"]),
            price_per_unit=r["price_per_unit"],
        )
        for r in raw_records
    ]
    volatility_results = evaluate_volatility(records, settings.price_surge_exclude_pct)
    passing_prices = filter_passing(volatility_results)
    passing_categories = sorted({r.product_name for r in passing_prices})

    apc_sites_path = data_dir / "apc_sites.json"
    if apc_sites_path.exists():
        apc_products = products_with_apc_priority(load_apc_sites(apc_sites_path))
    else:
        apc_products = set()

    calendar_items = load_seasonal_calendar(seasonal_calendar_path)
    this_month_map = category_variety_map(items_for_month(calendar_items, target_month))
    seasonal_variety_map = {
        category: varieties
        for category, varieties in this_month_map.items()
        if category in passing_categories
    }
    upcoming = upcoming_items(calendar_items, target_month, lookahead_months=1)

    variety_map = load_variety_map(variety_map_path)
    fallback_categories = [c for c in passing_categories if c not in seasonal_variety_map]
    fallback_map = expand_varieties(fallback_categories, variety_map)
    combined_map = {**fallback_map, **seasonal_variety_map}

    search_volumes = _load_json_or(data_dir / "search_volumes.json", {})
    competitor_counts = _load_json_or(data_dir / "competitor_counts.json", {})
    search_trends = _load_json_or(data_dir / "search_trends.json", {})

    all_candidates: list[VarietyCandidate] = []
    all_missing: list[str] = []
    for base_product, varieties in combined_map.items():
        candidates, missing = build_candidates(
            base_product, varieties, search_volumes, competitor_counts, search_trends
        )
        all_candidates.extend(candidates)
        all_missing.extend(missing)
    ranking = rank_blue_ocean(all_candidates, min_search_volume=settings.min_blue_ocean_search_volume)

    return ProductSelectionReport(
        target_month=target_month,
        passing_price_items=passing_prices,
        apc_priority_products=apc_products,
        seasonal_matched_categories=set(seasonal_variety_map.keys()),
        upcoming_next_month=upcoming,
        blue_ocean_ranking=ranking,
        blue_ocean_missing_competitor_data=all_missing,
    )
