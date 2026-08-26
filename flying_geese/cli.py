"""CLI 진입점: python -m flying_geese.cli run | run-live | select"""
from __future__ import annotations

import argparse
import sys

from flying_geese.pipeline import run_demo_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="농수산물 위탁판매 자동화 파이프라인")
    parser.add_argument(
        "command",
        choices=["run", "run-live", "select"],
        help=(
            "run: data/sample 기반 데모(1~5단계), "
            "run-live: 실 API 연동(1~5단계, 사전 설정 필요), "
            "select: API 키 없이 data/manual/ 수동 리서치 데이터로 1~2단계(상품 선정)만 실행"
        ),
    )
    args = parser.parse_args()

    if args.command == "run":
        report = run_demo_pipeline()
        _print_report(report)
    elif args.command == "run-live":
        from flying_geese.live_pipeline import run_live_pipeline

        try:
            report = run_live_pipeline()
        except (RuntimeError, FileNotFoundError) as exc:
            print(f"실전 파이프라인 실행 불가: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        _print_report(report)
    elif args.command == "select":
        from flying_geese.product_selection import run_product_selection

        try:
            report = run_product_selection()
        except FileNotFoundError as exc:
            print(f"상품 선정 실행 불가: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        _print_product_selection(report)


def _print_product_selection(report) -> None:
    print(f"=== 1단계: {report.target_month}월 제철 캘린더 & 폭등 제외 후 통과 품목 ===")
    for item in report.passing_price_items:
        in_season = "제철" if item.product_name in report.seasonal_matched_categories else "비수기"
        print(f"  - {item.product_name} [{in_season}]: 최근가 {item.latest_price:,.0f}원")
    print(f"  스마트 APC 우선 연동 품목: {sorted(report.apc_priority_products)}")
    if report.upcoming_next_month:
        preview = ", ".join(f"{i.category}({i.variety_keyword})" for i in report.upcoming_next_month)
        print(f"  다음 달 제철 예정 (사전예약 마케팅 후보): {preview}")

    print("\n=== 2단계: 블루오션 스코어링 상위 품종 ===")
    for candidate in report.blue_ocean_ranking:
        print(
            f"  - {candidate.variety_keyword} ({candidate.base_product}): "
            f"최종점수 {candidate.trending_score:.1f} "
            f"(블루오션지수 {candidate.blue_ocean_index:.1f} × 검색모멘텀 {candidate.search_trend_ratio:.2f}) "
            f"(검색량 {candidate.monthly_search_volume:,} / 경쟁상품 {candidate.competitor_product_count:,})"
        )
    if report.blue_ocean_missing_competitor_data:
        print(f"  ⚠ 경쟁상품 데이터 없음(스코어링 제외): {report.blue_ocean_missing_competitor_data}")


def _print_report(report) -> None:
    _print_product_selection(report)

    print("\n=== 3단계: 공급처 신뢰도 평가 ===")
    for evaluation in report.supplier_evaluations:
        status = "통과" if evaluation.passed else f"제외: {', '.join(evaluation.reasons)}"
        print(
            f"  - {evaluation.supplier.supplier_name}: 신뢰점수 {evaluation.trust_score} - {status}"
        )

    print("\n=== 4단계: 마진 & 목표 역산 시뮬레이션 ===")
    sim = report.simulation
    print(f"  목표 월매출: {sim.target_monthly_revenue:,}원")
    print(f"  필요 일 판매건수: {sim.required_daily_orders} / 월 판매건수: {sim.required_monthly_orders}")
    print(f"  예상 월 총마진: {sim.expected_gross_margin:,}원")
    print(f"  플랫폼 판매 수수료: -{sim.platform_fee:,}원")
    print(f"  예상 월 순수익: {sim.expected_net_profit:,}원")
    for tier, detail in sim.tier_breakdown.items():
        print(f"    · {tier}: {detail}")
    cf = report.cashflow
    print(
        f"  필요 운전자금(정산주기 {cf.settlement_cycle_days}일 기준): {cf.working_capital_required:,}원"
    )

    print("\n=== 5단계: 주문 발주 & 배송 처리 ===")
    print(f"  발주서 생성 완료: {report.purchase_order_path}")
    print(f"  발송 처리 완료 건수: {len(report.dispatched_orders)}")
    print(f"  송장 미수집 주문: {report.missing_tracking_order_ids}")
    print(f"  배송 상태 요약: {report.shipping_summary}")


if __name__ == "__main__":
    main()
