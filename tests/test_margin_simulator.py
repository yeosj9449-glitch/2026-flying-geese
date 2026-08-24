import pytest

from flying_geese.models import ProductMixItem, ProductTier
from flying_geese.stage4_simulator.cashflow import project_cashflow
from flying_geese.stage4_simulator.margin_simulator import simulate


def test_simulate_default_mix_hits_target_revenue_scale():
    result = simulate(target_monthly_revenue=5_000_000)
    assert result.required_monthly_orders > 0
    total_tier_revenue = sum(t["revenue"] for t in result.tier_breakdown.values())
    assert abs(total_tier_revenue - 5_000_000) < 50_000
    assert result.expected_net_profit > 0


def test_simulate_rejects_invalid_mix_ratio():
    bad_mix = [
        ProductMixItem(ProductTier.STANDARD, 30_000, 0.15, 0.5),
        ProductMixItem(ProductTier.PREMIUM, 60_000, 0.18, 0.6),
    ]
    with pytest.raises(ValueError):
        simulate(5_000_000, mix=bad_mix)


def test_project_cashflow_scales_with_settlement_cycle():
    cf14 = project_cashflow(5_000_000, settlement_cycle_days=14)
    cf7 = project_cashflow(5_000_000, settlement_cycle_days=7)
    assert cf14.working_capital_required == pytest.approx(cf7.working_capital_required * 2, rel=0.01)
