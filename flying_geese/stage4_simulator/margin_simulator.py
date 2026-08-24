"""상시 제철품목 vs 프리미엄 선물세트 믹스 기반 목표 매출 역산 시뮬레이터."""
from __future__ import annotations

from flying_geese.models import ProductMixItem, ProductTier, SimulationResult

DEFAULT_MIX = [
    ProductMixItem(tier=ProductTier.STANDARD, avg_price=30_000, margin_rate=0.15, mix_ratio=0.7),
    ProductMixItem(tier=ProductTier.PREMIUM, avg_price=60_000, margin_rate=0.18, mix_ratio=0.3),
]


def simulate(
    target_monthly_revenue: int,
    mix: list[ProductMixItem] | None = None,
    selling_days_per_month: int = 30,
) -> SimulationResult:
    mix = mix or DEFAULT_MIX
    total_ratio = sum(item.mix_ratio for item in mix)
    if abs(total_ratio - 1.0) > 1e-6:
        raise ValueError(f"mix_ratio 합계는 1.0이어야 합니다 (현재 {total_ratio}).")

    weighted_avg_price = sum(item.avg_price * item.mix_ratio for item in mix)
    required_monthly_orders = round(target_monthly_revenue / weighted_avg_price)
    required_daily_orders = required_monthly_orders / selling_days_per_month

    tier_breakdown: dict[str, dict[str, float]] = {}
    total_gross_margin = 0.0
    for item in mix:
        tier_orders = required_monthly_orders * item.mix_ratio
        tier_revenue = tier_orders * item.avg_price
        tier_margin = tier_revenue * item.margin_rate
        total_gross_margin += tier_margin
        tier_breakdown[item.tier.value] = {
            "monthly_orders": round(tier_orders, 1),
            "revenue": round(tier_revenue),
            "gross_margin": round(tier_margin),
        }

    return SimulationResult(
        target_monthly_revenue=target_monthly_revenue,
        required_daily_orders=round(required_daily_orders, 2),
        required_monthly_orders=required_monthly_orders,
        expected_gross_margin=round(total_gross_margin),
        expected_net_profit=round(total_gross_margin),
        tier_breakdown=tier_breakdown,
    )
