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
    platform_fee: float = 0.0  # 마진에서 차감된 플랫폼 판매 수수료


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


# ---------------------------------------------------------------------------
# 소싱 관리 (프리미엄 키즈 큐레이션 공급처 발굴 → 컨택 → 샘플 → 입점)
# ---------------------------------------------------------------------------
class SourcingStage(str, Enum):
    DISCOVERED = "발굴"
    CONTACTED = "컨택"
    SAMPLE_REQUESTED = "샘플요청"
    SAMPLE_REVIEW = "샘플검수"
    ONBOARDED = "입점"
    ON_HOLD = "보류"
    DROPPED = "탈락"


class SourcingGrade(str, Enum):
    KIDS = "S 키즈전용"  # 필수 1·2 통과 + 아이 기준(3) 전부 확인
    PASS = "A 입점가능"  # 필수 1·2 통과
    FIXABLE = "B 보완필요"  # 인증은 있으나 조회/검사서 등 서류가 아직 미비
    REJECT = "X 입점불가"  # 허용 인증 자체가 없음


@dataclass
class SupplierLead:
    lead_id: str
    supplier_name: str
    product_type: str  # 과일 / 농산 / 수산 / 축산
    items: list[str] = field(default_factory=list)
    region: str = ""
    source_channel: str = ""  # 발굴 경로 (친환경인증정보시스템, 지자체몰 등)
    contact_name: str = ""
    phone: str = ""
    email: str = ""
    stage: SourcingStage = SourcingStage.DISCOVERED
    # 필수 1: 인증
    cert_type: str = ""
    cert_number: str = ""
    cert_expiry: date | None = None
    cert_verified_on: date | None = None  # 친환경인증관리정보시스템에서 직접 조회한 날
    # 필수 2: 안전성 검사 (농산: 잔류농약 / 수산: 중금속·방사능)
    safety_test_type: str = ""
    safety_test_on: date | None = None
    # 3: 아이 기준
    kid_bite_size: bool = False
    kid_small_pack: bool = False
    kid_no_additive: bool = False
    # 4: 품질
    brix: float | None = None
    harvest_to_ship_days: int | None = None
    cold_chain: bool = False
    # 5: 스토리
    story_available: bool = False
    next_action: str = ""
    next_action_date: date | None = None
    notes: str = ""


@dataclass
class ContactLog:
    lead_id: str
    contacted_on: date | None
    channel: str
    summary: str
    outcome: str = ""


@dataclass
class SampleInspection:
    lead_id: str
    item: str
    received_on: date | None
    shipping_days: int | None = None  # 주문 → 수령 일수
    brix: float | None = None
    freshness_score: int | None = None  # 1~5
    taste_score: int | None = None
    packaging_score: int | None = None
    kid_fit_score: int | None = None  # 크기/손질 편의 등 아이 기준 체감
    notes: str = ""

    def scores(self) -> list[int]:
        return [
            s
            for s in (self.freshness_score, self.taste_score, self.packaging_score, self.kid_fit_score)
            if s is not None
        ]

    @property
    def passed(self) -> bool | None:
        """평균 4.0 이상이고 2점 이하 항목이 하나도 없어야 통과. 점수 미입력이면 None."""
        scores = self.scores()
        if not scores:
            return None
        return sum(scores) / len(scores) >= 4.0 and min(scores) > 2


@dataclass
class LeadEvaluation:
    lead: SupplierLead
    grade: SourcingGrade
    score: int  # 0~100
    cert_ok: bool
    safety_ok: bool
    kids_ok: bool
    missing: list[str] = field(default_factory=list)  # 미충족 항목 → 다음 액션으로 변환
    warnings: list[str] = field(default_factory=list)
    suggested_actions: list[str] = field(default_factory=list)
    sample_passed: bool | None = None
