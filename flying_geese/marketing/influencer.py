"""육아 마이크로 인플루언서 시딩 · 공구 관리.

influencers.csv (보유 리스트를 그대로 붙여넣고 칸만 맞추면 됨)를 읽어
  - 시딩 우선순위 점수 (아이 월령 적합도 × 참여율 × 팔로워 구간)
  - 상태 퍼널 (후보 → DM발송 → 수락 → 발송완료 → 게시완료 → 공구협의 → 공구진행)
  - 할 일 (DM 무응답 재연락, 게시 리마인드)
  - 공구 제안 후보, 쿠폰 매출 기반 시딩 ROI
를 계산해 대시보드 엑셀로 만든다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from openpyxl import Workbook

from flying_geese.tabular import parse_bool, parse_date, parse_float, parse_int, pick, read_csv_rows
from flying_geese.xlsx_style import FILL_GOOD, FILL_KIDS, write_table, write_title

STATUSES = ["후보", "DM발송", "수락", "발송완료", "게시완료", "공구협의", "공구진행", "거절"]
DM_FOLLOW_UP_DAYS = 5
POST_REMIND_DAYS = 7
GROUPBUY_MIN_ER = 0.03
GROUPBUY_MIN_COUPON_ORDERS = 5


@dataclass
class Influencer:
    handle: str
    platform: str = "인스타그램"
    followers: int = 0
    avg_likes: float = 0.0
    avg_comments: float = 0.0
    child_months: int | None = None  # 첫째/주력 콘텐츠 아이의 월령
    region: str = ""
    contact: str = ""
    status: str = "후보"
    dm_sent_on: date | None = None
    shipped_on: date | None = None
    posted_on: date | None = None
    post_url: str = ""
    coupon_code: str = ""
    coupon_orders: int = 0
    coupon_revenue: float = 0.0
    seeding_cost: float = 0.0  # 상품 원가 + 배송비
    groupbuy_ok: bool = False
    notes: str = ""

    @property
    def engagement_rate(self) -> float:
        return (self.avg_likes + self.avg_comments) / self.followers if self.followers else 0.0

    @property
    def tier(self) -> str:
        if self.followers < 10_000:
            return "나노"
        if self.followers <= 100_000:
            return "마이크로"
        if self.followers <= 500_000:
            return "미드"
        return "매크로"

    @property
    def roi(self) -> float | None:
        return self.coupon_revenue / self.seeding_cost if self.seeding_cost else None


@dataclass
class InfluencerEvaluation:
    influencer: Influencer
    priority: float
    persona: str
    todos: list[str] = field(default_factory=list)
    groupbuy_candidate: bool = False


def load_influencers(path: str | Path) -> list[Influencer]:
    rows = []
    for row in read_csv_rows(path):
        handle = pick(row, "핸들", "계정", "아이디")
        if not handle:
            continue
        status = pick(row, "상태") or "후보"
        rows.append(
            Influencer(
                handle=handle,
                platform=pick(row, "플랫폼") or "인스타그램",
                followers=parse_int(pick(row, "팔로워")) or 0,
                avg_likes=parse_float(pick(row, "평균좋아요")) or 0.0,
                avg_comments=parse_float(pick(row, "평균댓글")) or 0.0,
                child_months=parse_int(pick(row, "아이개월수", "아이월령")),
                region=pick(row, "지역"),
                contact=pick(row, "연락처", "DM"),
                status=status if status in STATUSES else "후보",
                dm_sent_on=parse_date(pick(row, "DM발송일")),
                shipped_on=parse_date(pick(row, "발송일")),
                posted_on=parse_date(pick(row, "게시일")),
                post_url=pick(row, "게시URL"),
                coupon_code=pick(row, "쿠폰코드"),
                coupon_orders=parse_int(pick(row, "쿠폰주문수")) or 0,
                coupon_revenue=parse_float(pick(row, "쿠폰매출")) or 0.0,
                seeding_cost=parse_float(pick(row, "시딩원가")) or 0.0,
                groupbuy_ok=parse_bool(pick(row, "공구가능")),
                notes=pick(row, "메모"),
            )
        )
    return rows


def persona_fit(child_months: int | None) -> tuple[float, str]:
    """아이 월령 → (적합도, 페르소나). A(이유식기)가 핵심, C(선물)는 월령과 무관해 별도 운영."""
    if child_months is None:
        return 0.5, "미상"
    if 6 <= child_months <= 24:
        return 1.0, "A 이유식맘"
    if child_months < 6:
        return 0.8, "A 예비(곧 이유식)"
    if child_months <= 60:
        return 0.7, "B 유아간식맘"
    if child_months <= 120:
        return 0.5, "B 초등간식맘"
    return 0.3, "기타"


def _tier_weight(followers: int) -> float:
    if 10_000 <= followers <= 100_000:
        return 1.0
    if 3_000 <= followers < 10_000:
        return 0.8
    if 100_000 < followers <= 300_000:
        return 0.7
    return 0.4


def evaluate_influencer(inf: Influencer, today: date) -> InfluencerEvaluation:
    fit, persona = persona_fit(inf.child_months)
    er_score = min(inf.engagement_rate / 0.05, 1.0)  # 참여율 5% 이상이면 만점
    priority = round(100 * (0.4 * fit + 0.4 * er_score + 0.2 * _tier_weight(inf.followers)), 1)

    todos: list[str] = []
    if inf.status == "DM발송" and inf.dm_sent_on and (today - inf.dm_sent_on).days >= DM_FOLLOW_UP_DAYS:
        todos.append(f"DM 무응답 {(today - inf.dm_sent_on).days}일 - 재연락 1회 후 종료")
    if inf.status == "수락" and not inf.shipped_on:
        todos.append("주소 받고 상품 발송 (발송일 기록)")
    if inf.status == "발송완료" and inf.shipped_on and not inf.posted_on:
        if (today - inf.shipped_on).days >= POST_REMIND_DAYS:
            todos.append("게시 리마인드 (협찬 표기 '광고/협찬' 안내 포함)")
    if inf.status == "게시완료" and not inf.coupon_code:
        todos.append("전용 쿠폰코드 발급해 성과 추적")

    groupbuy = (
        inf.status in ("게시완료", "공구협의")
        and inf.groupbuy_ok
        and (inf.engagement_rate >= GROUPBUY_MIN_ER or inf.coupon_orders >= GROUPBUY_MIN_COUPON_ORDERS)
    )
    if groupbuy and inf.status == "게시완료":
        todos.append("공구 제안 (사전예약형 3~5일, 우리 스토어 + 전용 링크/쿠폰)")
    return InfluencerEvaluation(inf, priority, persona, todos, groupbuy)


def evaluate_all(influencers: list[Influencer], today: date) -> list[InfluencerEvaluation]:
    return sorted((evaluate_influencer(i, today) for i in influencers), key=lambda e: -e.priority)


def write_influencer_dashboard(
    evaluations: list[InfluencerEvaluation], path: Path, today: date, using_examples: bool = False
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "요약"
    subtitle = f"기준일 {today.isoformat()} · 총 {len(evaluations)}명"
    if using_examples:
        subtitle += " · ⚠ 예시 데이터"
    row = write_title(sheet, "인플루언서 시딩 대시보드", subtitle)
    funnel = [[s, sum(1 for e in evaluations if e.influencer.status == s)] for s in STATUSES]
    row = write_table(sheet, row, ["상태", "인원"], funnel, [14, 10]) + 2
    posted = [e for e in evaluations if e.influencer.seeding_cost]
    cost = sum(e.influencer.seeding_cost for e in posted)
    revenue = sum(e.influencer.coupon_revenue for e in posted)
    stats = [
        ["시딩 원가 합계", round(cost)],
        ["쿠폰 매출 합계", round(revenue)],
        ["시딩 ROI", f"{revenue / cost:.0%}" if cost else "-"],
        ["공구 제안 후보", sum(1 for e in evaluations if e.groupbuy_candidate)],
    ]
    write_table(sheet, row, ["지표", "값"], stats)
    sheet.freeze_panes = None

    sheet = workbook.create_sheet("우선순위")
    start = write_title(sheet, "시딩 우선순위", "점수 = 아이 월령 적합 40% + 참여율 40% + 팔로워 구간 20%")
    rows = [
        [e.priority, e.influencer.handle, e.influencer.platform, e.influencer.followers, e.influencer.tier,
         f"{e.influencer.engagement_rate:.1%}", e.influencer.child_months, e.persona, e.influencer.region,
         e.influencer.status, "Y" if e.influencer.groupbuy_ok else "", e.influencer.contact]
        for e in evaluations
    ]
    write_table(
        sheet, start,
        ["점수", "핸들", "플랫폼", "팔로워", "구간", "참여율", "아이월령", "페르소나", "지역", "상태", "공구가능", "연락처"],
        rows, [7, 20, 10, 9, 8, 7, 8, 16, 10, 9, 8, 18],
    )
    for offset, e in enumerate(evaluations, start=1):
        if e.persona.startswith("A"):
            sheet.cell(row=start + offset, column=8).fill = FILL_KIDS

    sheet = workbook.create_sheet("할 일")
    start = write_title(sheet, "할 일")
    todo_rows = [[e.influencer.handle, e.influencer.status, t] for e in evaluations for t in e.todos]
    write_table(sheet, start, ["핸들", "상태", "할 일"], todo_rows, [20, 10, 70])

    sheet = workbook.create_sheet("공구·성과")
    start = write_title(sheet, "공구 후보 & 시딩 성과")
    perf_rows = [
        [e.influencer.handle, e.influencer.status, e.influencer.posted_on.isoformat() if e.influencer.posted_on else "",
         e.influencer.coupon_code, e.influencer.coupon_orders, round(e.influencer.coupon_revenue),
         round(e.influencer.seeding_cost), f"{e.influencer.roi:.0%}" if e.influencer.roi is not None else "-",
         "공구 제안" if e.groupbuy_candidate else "", e.influencer.post_url]
        for e in evaluations
        if e.influencer.status in ("발송완료", "게시완료", "공구협의", "공구진행")
    ]
    write_table(
        sheet, start,
        ["핸들", "상태", "게시일", "쿠폰", "쿠폰주문", "쿠폰매출", "시딩원가", "ROI", "공구", "게시URL"],
        perf_rows, [20, 10, 12, 10, 9, 10, 10, 8, 10, 40],
    )
    for offset, row_values in enumerate(perf_rows, start=1):
        if row_values[8]:
            sheet.cell(row=start + offset, column=9).fill = FILL_GOOD

    workbook.save(path)
    return path


def run_influencer_dashboard(
    marketing_dir: Path, output_path: Path, today: date | None = None
) -> tuple[list[InfluencerEvaluation], Path, bool]:
    today = today or date.today()
    real = marketing_dir / "influencers.csv"
    path, using_examples = (real, False) if real.exists() else (marketing_dir / "influencers.example.csv", True)
    evaluations = evaluate_all(load_influencers(path), today)
    return evaluations, write_influencer_dashboard(evaluations, output_path, today, using_examples), using_examples
