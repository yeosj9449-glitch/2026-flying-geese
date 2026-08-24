"""CS 위험 공급처 자동 배제 필터."""
from __future__ import annotations

from flying_geese.config import Settings
from flying_geese.models import Supplier, SupplierEvaluation
from flying_geese.stage3_supplier.supplier_metrics import trust_score


def evaluate_supplier(supplier: Supplier, settings: Settings) -> SupplierEvaluation:
    reasons: list[str] = []

    if supplier.fulfillment_rate < settings.min_supplier_fulfillment_rate:
        reasons.append(
            f"당일 출하 이행률 미달 ({supplier.fulfillment_rate:.1%} < "
            f"{settings.min_supplier_fulfillment_rate:.1%})"
        )
    if supplier.return_rate > settings.max_supplier_return_rate:
        reasons.append(
            f"반품률 초과 ({supplier.return_rate:.1%} > {settings.max_supplier_return_rate:.1%})"
        )
    if supplier.avg_delivery_hours > settings.max_supplier_avg_delivery_hours:
        reasons.append(
            f"평균 배송 소요시간 초과 ({supplier.avg_delivery_hours:.1f}h > "
            f"{settings.max_supplier_avg_delivery_hours:.1f}h)"
        )

    return SupplierEvaluation(
        supplier=supplier,
        passed=not reasons,
        reasons=reasons,
        trust_score=trust_score(supplier),
    )


def evaluate_suppliers(
    suppliers: list[Supplier], settings: Settings
) -> list[SupplierEvaluation]:
    evaluations = [evaluate_supplier(s, settings) for s in suppliers]
    evaluations.sort(key=lambda e: e.trust_score, reverse=True)
    return evaluations


def passing_suppliers(evaluations: list[SupplierEvaluation]) -> list[Supplier]:
    return [e.supplier for e in evaluations if e.passed]
