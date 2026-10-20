"""CLI 진입점: python -m flying_geese.cli <command>

  run | run-live | select                   상품 선정·운영 파이프라인
  sourcing | sourcing-log                   프리미엄 키즈 큐레이션 소싱 관리
  keywords | influencers | season-check     마케팅 자동화 · 제철 검증
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from flying_geese.models import SourcingStage
from flying_geese.pipeline import run_demo_pipeline

ROOT_DIR = Path(__file__).resolve().parents[1]
SAMPLE_DIR = ROOT_DIR / "data" / "sample"
OUTPUT_DIR = ROOT_DIR / "output"


def main() -> None:
    parser = argparse.ArgumentParser(description="농수산물 위탁판매 자동화 파이프라인")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="data/sample 기반 데모(1~5단계)")
    sub.add_parser("run-live", help="실 API 연동(1~5단계, 사전 설정 필요)")
    sub.add_parser("select", help="API 키 없이 data/manual/ 수동 리서치 데이터로 1~2단계(상품 선정)만 실행")

    sub.add_parser("sourcing", help="소싱 관리 대시보드 생성 (data/sourcing/*.csv → output/sourcing_dashboard.xlsx)")
    log = sub.add_parser("sourcing-log", help="공급처 연락 1건 기록 (+ 단계/다음액션 갱신)")
    log.add_argument("lead_id")
    log.add_argument("--channel", default="전화", help="전화/문자/이메일/카톡/방문")
    log.add_argument("--summary", required=True, help="연락 내용")
    log.add_argument("--outcome", default="", help="결과")
    log.add_argument("--stage", choices=[s.value for s in SourcingStage], help="단계 변경")
    log.add_argument("--next-action", help="다음 액션")
    log.add_argument("--next-date", help="다음 액션 기한 (YYYY-MM-DD)")

    kw = sub.add_parser("keywords", help="네이버 검색광고 키워드 발굴·등급화 (→ output/keyword_report.xlsx)")
    kw.add_argument("--from-file", type=Path, help="키워드도구에서 내려받은 CSV 또는 API 응답 JSON")
    kw.add_argument("--items", help="이번에 볼 품목만 (쉼표 구분, 예: 감귤,딸기)")
    kw.add_argument("--with-shopping", action="store_true", help="네이버 쇼핑 상품 수로 포화도까지 산정")

    sub.add_parser("influencers", help="인플루언서 시딩 대시보드 (→ output/influencer_dashboard.xlsx)")

    season = sub.add_parser("season-check", help="반입량·검색량 시계열로 제철/판매 적기 검증")
    season.add_argument("--arrivals", type=Path, default=SAMPLE_DIR / "arrivals.example.csv", help="월별 반입량 CSV")
    season.add_argument("--search", type=Path, default=SAMPLE_DIR / "search_seasonality.example.csv", help="월별 검색지수 CSV")
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
    elif args.command == "sourcing":
        from flying_geese.sourcing.runner import run_sourcing_dashboard

        _print_sourcing(run_sourcing_dashboard())
    elif args.command == "sourcing-log":
        from flying_geese.sourcing.runner import log_contact

        try:
            path = log_contact(
                args.lead_id, args.channel, args.summary, args.outcome,
                stage=args.stage, next_action=args.next_action, next_action_date=args.next_date,
            )
        except (FileNotFoundError, ValueError) as exc:
            print(f"기록 실패: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        print(f"연락 기록 완료: {path}")
    elif args.command == "keywords":
        from flying_geese.marketing.keyword_runner import run_keyword_discovery

        items = [i.strip() for i in args.items.split(",")] if args.items else None
        _print_keywords(run_keyword_discovery(stats_file=args.from_file, items=items, with_shopping=args.with_shopping))
    elif args.command == "influencers":
        from flying_geese.marketing.influencer import run_influencer_dashboard
        from flying_geese.marketing.keyword_discovery import DEFAULT_MARKETING_DIR

        evaluations, path, using_examples = run_influencer_dashboard(
            DEFAULT_MARKETING_DIR, OUTPUT_DIR / "influencer_dashboard.xlsx"
        )
        _print_influencers(evaluations, path, using_examples)
    elif args.command == "season-check":
        _print_season_check(args.arrivals, args.search)


def _print_sourcing(report) -> None:
    if report.using_examples:
        print("⚠ data/sourcing/leads.csv가 없어 예시 데이터로 실행했습니다 (leads.example.csv를 복사해 채우세요).")
    print("=== 소싱 퍼널 ===")
    print("  " + " → ".join(f"{k} {v}" for k, v in report.summary.stage_counts.items()))
    print("  등급: " + ", ".join(f"{k} {v}" for k, v in report.summary.grade_counts.items()))
    print(f"  키즈 전용 카테고리 확보 품목: {', '.join(report.summary.kids_category_items) or '없음'}")
    print("\n=== 할 일 (상위 10) ===")
    for todo in report.summary.todos[:10]:
        flag = "⚠지연 " if todo.overdue else ""
        due = todo.due.isoformat() if todo.due else "-"
        print(f"  {flag}[{due}] {todo.supplier_name}: {todo.action}")
    if report.summary.warnings:
        print("\n=== 경고 ===")
        for name, warning in report.summary.warnings:
            print(f"  - {name}: {warning}")
    print(f"\n대시보드: {report.dashboard_path}")


def _print_keywords(result) -> None:
    from flying_geese.marketing.keyword_discovery import GRADE_ORDER

    print(f"=== 키워드 발굴 ({result.source}) ===")
    for grade in GRADE_ORDER:
        group = [k for k in result.keywords if k.grade == grade]
        top = ", ".join(f"{k.stat.keyword}({k.stat.total_volume:,})" for k in group[:8])
        print(f"  {grade}: {len(group)}개  {top}")
    movers = [k for k in result.keywords if k.trend == "급상승"]
    if movers:
        print(f"  급상승: {', '.join(k.stat.keyword for k in movers[:10])}")
    if result.bid_recommendations:
        print("\n=== 입찰 조정 제안 (우선순위 순) ===")
        for rec in result.bid_recommendations[:10]:
            print(f"  [{rec.priority}] {rec.perf.keyword}: {rec.action} - {rec.reason}")
    print(f"\n리포트: {result.report_path}\n등록용 목록: {result.upload_path}")
    if result.db_path:
        print(f"키워드 DB(누적): {result.db_path}")


def _print_influencers(evaluations, path, using_examples) -> None:
    if using_examples:
        print("⚠ data/marketing/influencers.csv가 없어 예시 데이터로 실행했습니다.")
    print("=== 시딩 우선순위 (상위 10) ===")
    for e in evaluations[:10]:
        inf = e.influencer
        print(f"  {e.priority:5.1f}  {inf.handle} ({inf.followers:,} / 참여율 {inf.engagement_rate:.1%} / {e.persona}) - {inf.status}")
    todos = [(e.influencer.handle, t) for e in evaluations for t in e.todos]
    if todos:
        print("\n=== 할 일 ===")
        for handle, todo in todos:
            print(f"  - {handle}: {todo}")
    print(f"\n대시보드: {path}")


def _print_season_check(arrivals: Path, search: Path) -> None:
    from flying_geese.stage1_calendar.season_verifier import load_monthly_series, verify_seasons
    from flying_geese.stage1_calendar.seasonal_calendar import load_seasonal_calendar

    if "example" in arrivals.name:
        print("⚠ 예시(가상값) 시계열로 실행했습니다. --arrivals/--search에 실제 통계 CSV를 지정하세요.")
    supply = load_monthly_series(arrivals)
    demand = load_monthly_series(search) if search.exists() else None
    calendar = load_seasonal_calendar(SAMPLE_DIR / "seasonal_calendar.json")
    print("품목 | 출하 성수기 | 검색 성수기 | 판매 적기 | 사전예약 오픈 | 캘린더 일치도")
    for check in verify_seasons(supply, demand, calendar):
        presale = f"{check.presale_month}월" if check.presale_month else "-"
        agreement = f"{check.agreement:.0%}" if check.agreement is not None else "-"
        print(
            f"  {check.item} | {check.supply_peaks} | {check.search_peaks or '-'} | "
            f"{check.sell_window} | {presale} | {agreement}"
        )
        for note in check.notes:
            print(f"      · {note}")


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
