"""CLI 진입점: python -m flying_geese.cli run | run-live | select | affiliate-plan | affiliate-draft | affiliate-report"""
from __future__ import annotations

import argparse
import sys

from flying_geese.pipeline import run_demo_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="농수산물 위탁판매 자동화 파이프라인")
    parser.add_argument(
        "command",
        choices=["run", "run-live", "select", "affiliate-plan", "affiliate-draft", "affiliate-report"],
        help=(
            "run: data/sample 기반 데모(1~5단계), "
            "run-live: 실 API 연동(1~5단계, 사전 설정 필요), "
            "select: API 키 없이 data/manual/ 수동 리서치 데이터로 1~2단계(상품 선정)만 실행, "
            "affiliate-plan: 쿠팡 파트너스 목표 수수료 역산(키 불필요), "
            "affiliate-draft: 키워드별 파트너스 상품 검색 → 게시물 초안 생성, "
            "affiliate-report: 이번 달 수수료 실적 및 월말 예상"
        ),
    )
    parser.add_argument("--keywords", nargs="*", default=[], help="affiliate-draft 키워드 목록")
    parser.add_argument(
        "--from-selection",
        action="store_true",
        help="affiliate-draft: data/manual 상품 선정 결과의 블루오션 상위 품종을 키워드로 사용",
    )
    parser.add_argument("--posts-per-day", type=float, default=3, help="affiliate-plan: 실제 발행 가능 게시물 수/일")
    args = parser.parse_args()

    if args.command.startswith("affiliate-"):
        _run_affiliate(args)
        return

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


def _run_affiliate(args) -> None:
    from flying_geese.config import load_settings

    settings = load_settings()
    if args.command == "affiliate-plan":
        _print_affiliate_plan(settings, args.posts_per_day)
        return

    from flying_geese.affiliate.coupang_partners_api import CoupangPartnersClient

    client = CoupangPartnersClient(settings)
    if not settings.coupang_partners_ready():
        print(
            "COUPANG_PARTNERS_ACCESS_KEY / SECRET_KEY가 없습니다 (파트너스 최종 승인 후 발급). "
            "키 없이 가능한 것은 affiliate-plan 입니다.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    if args.command == "affiliate-draft":
        from flying_geese.affiliate.pipeline import keywords_from_selection, run_affiliate_drafts

        keywords = list(args.keywords)
        if args.from_selection:
            from flying_geese.product_selection import run_product_selection

            keywords += keywords_from_selection(run_product_selection())
        if not keywords:
            print("--keywords 또는 --from-selection 중 하나가 필요합니다.", file=sys.stderr)
            raise SystemExit(1)
        report = run_affiliate_drafts(keywords, client)
        print(f"초안 {len(report.draft_paths)}건 생성 (발행 전 TODO 섹션을 직접 채워주세요):")
        for path in report.draft_paths:
            print(f"  - {path}")
        if report.empty_keywords:
            print(f"  검색 결과 없음: {report.empty_keywords}")
        for keyword, error in report.failed_keywords.items():
            print(f"  ⚠ '{keyword}' 검색 실패: {error}")
    elif args.command == "affiliate-report":
        from datetime import date

        from flying_geese.affiliate.performance import progress_report

        today = date.today()
        rows = client.commission_report(today.strftime("%Y%m01"), today.strftime("%Y%m%d"))
        progress = progress_report(rows, settings.affiliate_target_monthly_commission, today)
        print(f"=== {today:%Y-%m} 쿠팡 파트너스 실적 (발생 기준, 정산은 익익월) ===")
        print(f"  목표: {progress.target_commission:,}원 / 누적: {progress.earned_to_date:,}원")
        print(f"  일평균: {progress.daily_run_rate:,}원 → 월말 예상: {progress.projected_month_end:,}원")
        print(f"  남은 기간 필요 일평균: {progress.required_daily_for_target:,}원")
        if progress.observed_click_to_order_rate is not None:
            print(
                f"  클릭 {progress.clicks:,} / 주문 {progress.orders:,} "
                f"(전환율 {progress.observed_click_to_order_rate:.1%})"
            )
        print(f"  상태: {'목표 페이스' if progress.on_track else '목표 미달 페이스'}")


def _print_affiliate_plan(settings, posts_per_day: float) -> None:
    from flying_geese.affiliate.goal_calculator import (
        DEFAULT_SCENARIOS,
        MAX_SUSTAINABLE_POSTS_PER_DAY,
        plan_for_target,
        project_commission,
    )

    target = settings.affiliate_target_monthly_commission
    rate = settings.coupang_partners_commission_rate
    print(f"=== 목표 월 수수료 {target:,}원 역산 (수수료율 {rate:.1%}, 30일) ===")
    for scenario in DEFAULT_SCENARIOS:
        plan = plan_for_target(target, rate, scenario)
        verdict = "가능 범위" if plan.feasible else f"비현실적(1인 품질 유지 상한 {MAX_SUSTAINABLE_POSTS_PER_DAY}개/일 초과)"
        print(
            f"  [{plan.scenario}] 필요 매출 {plan.required_sales:,}원 → 주문 {plan.required_orders:,}건 "
            f"→ 클릭 {plan.required_clicks:,} → 조회 {plan.required_views:,} "
            f"→ 게시물 {plan.required_posts:,}개 (하루 {plan.required_posts_per_day}개) - {verdict}"
        )
    print(f"\n=== 하루 {posts_per_day:g}개 발행 시 30일 예상 수수료 ===")
    for scenario in DEFAULT_SCENARIOS:
        expected = project_commission(posts_per_day, rate, scenario)
        print(f"  [{scenario.name}] {expected:,}원")
    print("  ※ 전환율/조회수는 가정치입니다. 운영 1~2주 후 affiliate-report 실측값으로 보정하세요.")


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
