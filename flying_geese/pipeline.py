"""5단계 파이프라인 오케스트레이터.

실 서비스에서는 각 단계의 실제 API 클라이언트(KamisClient, NaverDatalabClient 등)를
주입하면 되고, 여기서는 API 키 없이도 전체 흐름을 검증할 수 있도록
data/sample/ 의 로컬 데이터로 동작하는 데모 파이프라인을 제공한다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from flying_geese.config import Settings, load_settings
from flying_geese.models import (
    OrderLine,
    OrderStatus,
    PriceRecord,
    SeasonalItem,
    SimulationResult,
    SupplierEvaluation,
    VarietyCandidate,
    VolatilityResult,
)
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
from flying_geese.stage3_supplier.risk_filter import evaluate_suppliers
from flying_geese.stage3_supplier.supplier_metrics import load_suppliers
from flying_geese.stage4_simulator.cashflow import CashflowProjection, project_cashflow
from flying_geese.stage4_simulator.margin_simulator import simulate
from flying_geese.stage5_automation.commerce_api import MockCommerceClient
from flying_geese.stage5_automation.purchase_order import generate_purchase_order_excel
from flying_geese.stage5_automation.shipping import (
    dispatch_orders,
    load_tracking_numbers_from_csv,
    shipping_status_summary,
)

DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "sample"


@dataclass
class PipelineReport:
    target_month: int
    passing_price_items: list[VolatilityResult]
    apc_priority_products: set[str]
    seasonal_matched_categories: set[str]
    upcoming_next_month: list[SeasonalItem]
    blue_ocean_ranking: list[VarietyCandidate]
    supplier_evaluations: list[SupplierEvaluation]
    simulation: SimulationResult
    cashflow: CashflowProjection
    purchase_order_path: Path
    dispatched_orders: list[OrderLine]
    missing_tracking_order_ids: list[str]
    shipping_summary: dict[str, int]


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _run_stage1(
    data_dir: Path, settings: Settings, target_month: int
) -> tuple[list[VolatilityResult], set[str], dict[str, list[str]], list[SeasonalItem]]:
    """도매가 검증 + 제철 캘린더 매칭.

    반환값: (폭등 제외 후 통과 품목, APC 우선 품목, 이번 달 제철이면서 가격이
    안정적인 대표품목 -> 추천 세부품종 매핑, 다음 달 제철 예정 미리보기)
    """
    raw_records = _load_json(data_dir / "price_records.json")
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
    passing = filter_passing(volatility_results)

    apc_sites = load_apc_sites(data_dir / "apc_sites.json")
    apc_products = products_with_apc_priority(apc_sites)

    calendar_items = load_seasonal_calendar(data_dir / "seasonal_calendar.json")
    this_month_map = category_variety_map(items_for_month(calendar_items, target_month))

    passing_categories = {r.product_name for r in passing}
    seasonal_variety_map = {
        category: varieties
        for category, varieties in this_month_map.items()
        if category in passing_categories
    }

    upcoming = upcoming_items(calendar_items, target_month, lookahead_months=1)

    return passing, apc_products, seasonal_variety_map, upcoming


def _run_stage2(
    data_dir: Path,
    passing_categories: list[str],
    seasonal_variety_map: dict[str, list[str]],
) -> list[VarietyCandidate]:
    """제철 캘린더에 매칭된 품종만 우선 채점하고, 캘린더에 없는 대표품목은
    품종 매핑표 전체를 훑는 기존 방식으로 폴백한다."""
    variety_map = load_variety_map(data_dir / "variety_map.json")
    search_volumes = _load_json(data_dir / "search_volumes.json")
    competitor_counts = _load_json(data_dir / "competitor_counts.json")

    fallback_categories = [c for c in passing_categories if c not in seasonal_variety_map]
    fallback_map = expand_varieties(fallback_categories, variety_map)

    combined_map = {**fallback_map, **seasonal_variety_map}

    all_candidates: list[VarietyCandidate] = []
    for base_product, varieties in combined_map.items():
        all_candidates.extend(
            build_candidates(base_product, varieties, search_volumes, competitor_counts)
        )
    return rank_blue_ocean(all_candidates)


def _run_stage3(data_dir: Path, settings: Settings) -> list[SupplierEvaluation]:
    suppliers = load_suppliers(data_dir / "suppliers.json")
    return evaluate_suppliers(suppliers, settings)


def _run_stage4(settings: Settings) -> tuple[SimulationResult, CashflowProjection]:
    simulation = simulate(settings.target_monthly_revenue)
    cashflow = project_cashflow(settings.target_monthly_revenue)
    return simulation, cashflow


def _run_stage5(
    data_dir: Path, output_dir: Path
) -> tuple[Path, list[OrderLine], list[str], dict[str, int]]:
    raw_orders = _load_json(data_dir / "orders.json")
    orders = [
        OrderLine(
            order_id=str(o["orderId"]),
            product_name=o["productName"],
            variety_keyword=o.get("varietyKeyword", o["productName"]),
            quantity=int(o["quantity"]),
            unit_price=int(o["unitPrice"]),
            supplier_id=o.get("supplierId", ""),
            buyer_name=o.get("buyerName", ""),
            buyer_address=o.get("buyerAddress", ""),
            buyer_phone=o.get("buyerPhone", ""),
            status=OrderStatus.NEW,
        )
        for o in raw_orders
    ]

    client = MockCommerceClient(orders)
    new_orders = client.fetch_new_orders()

    po_path = generate_purchase_order_excel(new_orders, output_dir / "purchase_order.xlsx")

    tracking_map = load_tracking_numbers_from_csv(data_dir / "tracking.csv")
    dispatched, missing = dispatch_orders(new_orders, tracking_map, client)
    summary = shipping_status_summary(orders)

    return po_path, dispatched, missing, summary


def run_demo_pipeline(
    data_dir: Path | None = None,
    output_dir: Path | None = None,
    target_month: int | None = None,
) -> PipelineReport:
    settings = load_settings()
    data_dir = data_dir or DEFAULT_DATA_DIR
    output_dir = output_dir or (Path(__file__).resolve().parent.parent / "output")
    target_month = target_month or date.today().month

    passing_prices, apc_products, seasonal_variety_map, upcoming = _run_stage1(
        data_dir, settings, target_month
    )
    passing_categories = sorted({r.product_name for r in passing_prices})
    blue_ocean_ranking = _run_stage2(data_dir, passing_categories, seasonal_variety_map)
    supplier_evaluations = _run_stage3(data_dir, settings)
    simulation, cashflow = _run_stage4(settings)
    po_path, dispatched, missing, shipping_summary = _run_stage5(data_dir, output_dir)

    return PipelineReport(
        target_month=target_month,
        passing_price_items=passing_prices,
        apc_priority_products=apc_products,
        seasonal_matched_categories=set(seasonal_variety_map.keys()),
        upcoming_next_month=upcoming,
        blue_ocean_ranking=blue_ocean_ranking,
        supplier_evaluations=supplier_evaluations,
        simulation=simulation,
        cashflow=cashflow,
        purchase_order_path=po_path,
        dispatched_orders=dispatched,
        missing_tracking_order_ids=missing,
        shipping_summary=shipping_summary,
    )
