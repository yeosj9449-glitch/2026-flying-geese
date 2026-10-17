"""목표 월 수수료 → 필요 매출/주문/클릭/조회수/게시물 수 역산.

쿠팡 파트너스 수수료는 "추천한 상품"이 아니라 링크 클릭 후 발생한 구매
금액(GMV)에 수수료율을 곱해 산정된다. 기본 수수료율은 약 3%로 알려져 있으나
카테고리/프로모션별로 다를 수 있으므로 COUPANG_PARTNERS_COMMISSION_RATE로
조정한다. 퍼널 전환율 시나리오는 업계 통념 수준의 "가정치"이며, 실제 운영
1~2주 데이터(performance.py)로 반드시 보정해야 한다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class FunnelAssumptions:
    name: str
    avg_order_value: int  # 클릭 후 발생한 구매 1건당 평균 결제금액(원)
    click_to_order_rate: float  # 링크 클릭 → 구매 전환율
    view_to_click_rate: float  # 콘텐츠 조회 → 링크 클릭률
    views_per_post_per_day: float  # 게시물 1개당 일평균 조회수 (신규 채널 기준)


DEFAULT_SCENARIOS: tuple[FunnelAssumptions, ...] = (
    FunnelAssumptions("보수적", 30_000, 0.03, 0.02, 5),
    FunnelAssumptions("기본", 40_000, 0.05, 0.04, 15),
    FunnelAssumptions("낙관적", 50_000, 0.08, 0.06, 40),
)

# 사람이 검수/보강하며 품질을 유지할 수 있는 1인 기준 하루 게시물 수 상한.
# 이를 넘는 대량 자동 발행은 저품질/스팸으로 분류돼 노출 제한이나 파트너스
# 이용 제한을 받을 위험이 크다.
MAX_SUSTAINABLE_POSTS_PER_DAY = 5


@dataclass(frozen=True)
class GoalPlan:
    scenario: str
    target_commission: int
    days: int
    required_sales: int
    required_orders: int
    required_clicks: int
    required_views: int
    required_posts: int
    required_posts_per_day: float
    feasible: bool


def plan_for_target(
    target_commission: int,
    commission_rate: float,
    assumptions: FunnelAssumptions,
    days: int = 30,
) -> GoalPlan:
    """목표 수수료를 달성하기 위해 필요한 퍼널 각 단계의 규모를 역산한다.

    게시물은 기간 동안 균등하게 발행된다고 가정하므로, 게시물 1개가 기간 내
    노출되는 평균 일수는 days / 2 이다(첫날 글은 30일, 마지막 날 글은 1일).
    """
    if commission_rate <= 0:
        raise ValueError("commission_rate는 0보다 커야 합니다.")

    required_sales = target_commission / commission_rate
    required_orders = math.ceil(required_sales / assumptions.avg_order_value)
    required_clicks = math.ceil(required_orders / assumptions.click_to_order_rate)
    required_views = math.ceil(required_clicks / assumptions.view_to_click_rate)
    avg_live_days = max(days / 2, 1)
    required_posts = math.ceil(
        required_views / (assumptions.views_per_post_per_day * avg_live_days)
    )
    posts_per_day = required_posts / days
    return GoalPlan(
        scenario=assumptions.name,
        target_commission=target_commission,
        days=days,
        required_sales=math.ceil(required_sales),
        required_orders=required_orders,
        required_clicks=required_clicks,
        required_views=required_views,
        required_posts=required_posts,
        required_posts_per_day=round(posts_per_day, 1),
        feasible=posts_per_day <= MAX_SUSTAINABLE_POSTS_PER_DAY,
    )


def project_commission(
    posts_per_day: float,
    commission_rate: float,
    assumptions: FunnelAssumptions,
    days: int = 30,
) -> int:
    """하루 posts_per_day개를 꾸준히 발행할 때 기간 내 예상 수수료(원)."""
    total_posts = posts_per_day * days
    views = total_posts * assumptions.views_per_post_per_day * max(days / 2, 1)
    sales = (
        views
        * assumptions.view_to_click_rate
        * assumptions.click_to_order_rate
        * assumptions.avg_order_value
    )
    return int(sales * commission_rate)
