"""전 단계 공용 데이터 모델."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum


# ---------------------------------------------------------------------------
# 1단계: 제철 캘린더 & 도매가
# ---------------------------------------------------------------------------
@dataclass
class PriceRecord:
    product_code: str
    product_name: str
    market: str
    trade_date: date
    price_per_unit: float
    unit: str = "kg"


@dataclass
class VolatilityResult:
    product_code: str
    product_name: str
    latest_price: float
    mom_change_pct: float | None  # 전월 대비
    yoy_change_pct: float | None  # 전년 대비
    excluded: bool
    exclude_reason: str = ""


@dataclass
class ApcSite:
    apc_id: str
    apc_name: str
    region: str
    top_products: list[str] = field(default_factory=list)
    is_smart_apc: bool = True


# ---------------------------------------------------------------------------
# 2단계: 세부 품종 세분화 & 블루오션 스코어링
# ---------------------------------------------------------------------------
@dataclass
class VarietyCandidate:
    base_product: str  # 예: 사과
    variety_keyword: str  # 예: 감홍사과
    monthly_search_volume: int
    competitor_product_count: int

    @property
    def blue_ocean_index(self) -> float:
        if self.competitor_product_count <= 0:
            return float(self.monthly_search_volume)
        return self.monthly_search_volume / self.competitor_product_count


# ---------------------------------------------------------------------------
# 3단계: 공급처 신뢰도 & CS 리스크
# ---------------------------------------------------------------------------
@dataclass
class Supplier:
    supplier_id: str
    supplier_name: str
    region: str
    fulfillment_rate: float  # 당일 출하 이행률 (0~1)
    avg_delivery_hours: float
    return_rate: float  # 반품률 (0~1)
    has_e_tracking: bool = False  # 전자송품장 적용 여부


@dataclass
class SupplierEvaluation:
    supplier: Supplier
    passed: bool
    reasons: list[str] = field(default_factory=list)
    trust_score: float = 0.0


# ---------------------------------------------------------------------------
# 4단계: 마진 & 목표 역산 시뮬레이터
# ---------------------------------------------------------------------------
class ProductTier(str, Enum):
    STANDARD = "상시 제철품목"
    PREMIUM = "프리미엄/시즌 선물세트"


@dataclass
class ProductMixItem:
    tier: ProductTier
    avg_price: int
    margin_rate: float
    mix_ratio: float  # 판매 건수 비중 (0~1)


@dataclass
class SimulationResult:
    target_monthly_revenue: int
    required_daily_orders: float
    required_monthly_orders: int
    expected_gross_margin: float
    expected_net_profit: float
    tier_breakdown: dict[str, dict[str, float]]


# ---------------------------------------------------------------------------
# 5단계: 주문 발주 & 배송 처리 자동화
# ---------------------------------------------------------------------------
class OrderStatus(str, Enum):
    NEW = "신규주문"
    PO_ISSUED = "발주완료"
    SHIPPED = "발송완료"
    CANCELLED = "취소"


@dataclass
class OrderLine:
    order_id: str
    product_name: str
    variety_keyword: str
    quantity: int
    unit_price: int
    supplier_id: str
    buyer_name: str
    buyer_address: str
    buyer_phone: str
    status: OrderStatus = OrderStatus.NEW
    tracking_number: str | None = None
