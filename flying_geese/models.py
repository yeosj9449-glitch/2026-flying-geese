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


@dataclass
class SeasonalItem:
    category: str  # KAMIS 등 도매가 조회 단위 대표 품목 (예: 사과)
    variety_keyword: str  # 이 시기에 미는 세부 품종 (예: 홍로사과)
    product_type: str  # 과일 / 농산 / 수산 등
    peak_months: list[int]  # 제철 구간 (1~12), 여러 달에 걸칠 수 있음

    def is_in_season(self, month: int) -> bool:
        return month in self.peak_months


# ---------------------------------------------------------------------------
# 2단계: 세부 품종 세분화 & 블루오션 스코어링
# ---------------------------------------------------------------------------
@dataclass
class VarietyCandidate:
    base_product: str  # 예: 사과
    variety_keyword: str  # 예: 감홍사과
    monthly_search_volume: int
    competitor_product_count: int
    search_trend_ratio: float = 1.0  # 최근 검색 모멘텀 (네이버 데이터랩 기반, 1.0=변화없음, >1 상승세)

    @property
    def blue_ocean_index(self) -> float:
        if self.competitor_product_count <= 0:
            return float(self.monthly_search_volume)
        return self.monthly_search_volume / self.competitor_product_count

    @property
    def trending_score(self) -> float:
        """블루오션 지수에 검색 모멘텀을 반영한 최종 스코어.

        상승세 키워드를 우대하되, 데이터랩 응답 이상치가 순위를 과도하게
        흔들지 않도록 모멘텀 배수를 0.5~2.0배로 clamp한다.
        """
        momentum = max(0.5, min(self.search_trend_ratio, 2.0))
        return self.blue_ocean_index * momentum


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
