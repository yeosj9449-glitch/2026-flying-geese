"""플랫폼 정산 주기를 고려한 필요 현금 흐름 계산."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CashflowProjection:
    daily_revenue: float
    settlement_cycle_days: int
    working_capital_required: float
    breakeven_day: int


def project_cashflow(
    monthly_revenue: int,
    settlement_cycle_days: int = 14,
    selling_days_per_month: int = 30,
) -> CashflowProjection:
    """정산 주기 동안 선지출되는 사입/배송 비용을 감당할 최소 운전자금을 추정한다.

    정산 전까지는 매출이 현금화되지 않으므로, 정산 주기(settlement_cycle_days) 동안
    발생하는 매출액만큼을 최소 운전자금으로 확보해야 한다.
    """
    daily_revenue = monthly_revenue / selling_days_per_month
    working_capital_required = daily_revenue * settlement_cycle_days
    return CashflowProjection(
        daily_revenue=round(daily_revenue, 2),
        settlement_cycle_days=settlement_cycle_days,
        working_capital_required=round(working_capital_required),
        breakeven_day=settlement_cycle_days,
    )
