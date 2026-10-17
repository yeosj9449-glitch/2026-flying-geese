"""월 목표 대비 실적 추적 및 월말 예상 수수료.

쿠팡 파트너스 수수료는 실적 발생 월 기준 익익월(약 45일 뒤)에 정산되고,
취소/반품분은 차감된다. 여기서 계산하는 값은 "발생 수수료"이며 실제 입금액과
시점이 다르다는 점에 유의한다.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date

from flying_geese.affiliate.coupang_partners_api import DailyCommission


@dataclass(frozen=True)
class ProgressReport:
    target_commission: int
    earned_to_date: int
    days_elapsed: int
    days_in_month: int
    daily_run_rate: int
    projected_month_end: int
    required_daily_for_target: int  # 남은 기간 동안 목표 달성에 필요한 일평균 수수료
    clicks: int
    orders: int
    observed_click_to_order_rate: float | None
    on_track: bool


def progress_report(
    rows: list[DailyCommission], target_commission: int, as_of: date
) -> ProgressReport:
    month_prefix = as_of.strftime("%Y%m")
    in_month = [
        r for r in rows if r.date.startswith(month_prefix) and r.date <= as_of.strftime("%Y%m%d")
    ]
    earned = sum(r.commission for r in in_month)
    clicks = sum(r.clicks for r in in_month)
    orders = sum(r.orders for r in in_month)
    days_in_month = calendar.monthrange(as_of.year, as_of.month)[1]
    days_elapsed = as_of.day
    run_rate = earned // days_elapsed
    projected = run_rate * days_in_month
    remaining_days = days_in_month - days_elapsed
    shortfall = max(target_commission - earned, 0)
    required_daily = shortfall // remaining_days if remaining_days else shortfall
    return ProgressReport(
        target_commission=target_commission,
        earned_to_date=earned,
        days_elapsed=days_elapsed,
        days_in_month=days_in_month,
        daily_run_rate=run_rate,
        projected_month_end=projected,
        required_daily_for_target=required_daily,
        clicks=clicks,
        orders=orders,
        observed_click_to_order_rate=(orders / clicks) if clicks else None,
        on_track=projected >= target_commission,
    )
