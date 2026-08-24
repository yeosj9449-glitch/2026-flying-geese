"""전년/전월 대비 도매가 폭등률 기반 자동 제외 필터."""
from __future__ import annotations

from collections import defaultdict

from flying_geese.models import PriceRecord, VolatilityResult


def _pct_change(old: float, new: float) -> float | None:
    if old <= 0:
        return None
    return (new - old) / old * 100.0


def evaluate_volatility(
    records: list[PriceRecord],
    surge_exclude_pct: float = 20.0,
) -> list[VolatilityResult]:
    """품목별 최신가 대비 전월/전년 가격을 비교해 폭등 품목을 표시한다.

    같은 product_code의 레코드를 날짜순으로 정렬한 뒤,
    - MoM: 최신 레코드보다 약 30일 이전에서 가장 가까운 레코드
    - YoY: 최신 레코드보다 약 365일 이전에서 가장 가까운 레코드
    를 기준으로 변동률을 계산한다.
    """
    by_product: dict[str, list[PriceRecord]] = defaultdict(list)
    for record in records:
        by_product[record.product_code].append(record)

    results: list[VolatilityResult] = []
    for product_code, rows in by_product.items():
        rows.sort(key=lambda r: r.trade_date)
        latest = rows[-1]

        mom_ref = _closest_by_offset(rows, latest, target_days=30)
        yoy_ref = _closest_by_offset(rows, latest, target_days=365)

        mom_pct = _pct_change(mom_ref.price_per_unit, latest.price_per_unit) if mom_ref else None
        yoy_pct = _pct_change(yoy_ref.price_per_unit, latest.price_per_unit) if yoy_ref else None

        exclude_reason = ""
        excluded = False
        for label, pct in (("전월", mom_pct), ("전년", yoy_pct)):
            if pct is not None and pct >= surge_exclude_pct:
                excluded = True
                exclude_reason = f"{label} 대비 {pct:.1f}% 폭등 (기준 {surge_exclude_pct}%)"
                break

        results.append(
            VolatilityResult(
                product_code=product_code,
                product_name=latest.product_name,
                latest_price=latest.price_per_unit,
                mom_change_pct=mom_pct,
                yoy_change_pct=yoy_pct,
                excluded=excluded,
                exclude_reason=exclude_reason,
            )
        )
    return results


def _closest_by_offset(
    rows: list[PriceRecord], latest: PriceRecord, target_days: int, tolerance_days: int = 10
) -> PriceRecord | None:
    best: PriceRecord | None = None
    best_diff = None
    for row in rows:
        if row is latest:
            continue
        age_days = (latest.trade_date - row.trade_date).days
        diff = abs(age_days - target_days)
        if diff <= tolerance_days and (best_diff is None or diff < best_diff):
            best, best_diff = row, diff
    return best


def filter_passing(results: list[VolatilityResult]) -> list[VolatilityResult]:
    """폭등 제외되지 않은 품목만 반환한다."""
    return [r for r in results if not r.excluded]
