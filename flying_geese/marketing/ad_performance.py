"""검색광고 성과 보고서 → 키워드별 입찰 조정 제안.

검색광고 관리시스템 > 보고서 > 키워드 단위 보고서를 CSV로 내려받아 넣으면
ROAS/전환/CTR 기준으로 '입찰 상향 / 유지 / 하향 / 일시중지'를 제안한다.
실제 입찰 변경은 사람이 확인 후 적용한다 (자동 변경은 하지 않음).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from flying_geese.tabular import parse_float, pick, read_csv_rows


@dataclass
class KeywordPerformance:
    keyword: str
    ad_group: str
    impressions: int
    clicks: int
    cost: float
    conversions: int
    revenue: float

    @property
    def ctr(self) -> float:
        return self.clicks / self.impressions if self.impressions else 0.0

    @property
    def roas(self) -> float | None:
        return self.revenue / self.cost if self.cost else None

    @property
    def cpc(self) -> float:
        return self.cost / self.clicks if self.clicks else 0.0


@dataclass
class BidRecommendation:
    perf: KeywordPerformance
    action: str
    reason: str
    priority: int  # 1=즉시 처리


@dataclass(frozen=True)
class BidRules:
    target_roas: float = 3.0  # 300%
    min_clicks: int = 20  # 이 미만이면 판단 보류
    min_impressions: int = 100
    target_aov: int = 60_000  # 목표 객단가 - 전환 없는 비용 한도 산정용
    low_ctr: float = 0.01

    @property
    def max_cost_without_conversion(self) -> float:
        # 목표 ROAS에서 허용되는 주문 1건당 광고비(=객단가/목표ROAS)를 전환 없이 쓰면 중지 검토
        return self.target_aov / self.target_roas


def load_performance(path: str | Path) -> list[KeywordPerformance]:
    rows = []
    for row in read_csv_rows(path):
        keyword = pick(row, "키워드", "keyword")
        if not keyword:
            continue
        rows.append(
            KeywordPerformance(
                keyword=keyword,
                ad_group=pick(row, "광고그룹", "광고그룹명"),
                impressions=int(parse_float(pick(row, "노출수")) or 0),
                clicks=int(parse_float(pick(row, "클릭수")) or 0),
                cost=parse_float(pick(row, "총비용(VAT포함,원)", "총비용", "비용")) or 0.0,
                conversions=int(parse_float(pick(row, "전환수", "총전환수")) or 0),
                revenue=parse_float(pick(row, "전환매출액(원)", "전환매출액", "총전환매출액(원)")) or 0.0,
            )
        )
    return rows


def recommend(perf: KeywordPerformance, rules: BidRules = BidRules()) -> BidRecommendation:
    roas = perf.roas
    if perf.conversions == 0 and perf.cost >= rules.max_cost_without_conversion:
        rec = BidRecommendation(perf, "일시중지", f"전환 없이 {perf.cost:,.0f}원 소진 (한도 {rules.max_cost_without_conversion:,.0f}원)", 1)
    elif perf.clicks < rules.min_clicks:
        if perf.impressions < rules.min_impressions:
            rec = BidRecommendation(perf, "입찰 +20%", "노출 부족 - 순위가 너무 낮음", 3)
        else:
            rec = BidRecommendation(perf, "유지(데이터 부족)", f"클릭 {perf.clicks}회 < {rules.min_clicks}회", 4)
    elif roas is not None and roas >= rules.target_roas * 1.5:
        rec = BidRecommendation(perf, "입찰 +15%", f"ROAS {roas:.0%} - 목표의 1.5배 이상, 노출 확대", 2)
    elif roas is not None and roas >= rules.target_roas:
        rec = BidRecommendation(perf, "유지", f"ROAS {roas:.0%} - 목표 달성", 5)
    elif roas is not None and roas < rules.target_roas * 0.5:
        rec = BidRecommendation(perf, "입찰 -30% 또는 중지", f"ROAS {roas:.0%} - 목표의 절반 미만", 1)
    else:
        roas_text = f"{roas:.0%}" if roas is not None else "-"
        rec = BidRecommendation(perf, "입찰 -15%", f"ROAS {roas_text} - 목표 미달", 2)

    if perf.impressions >= 1000 and perf.ctr < rules.low_ctr:
        rec.reason += f" / CTR {perf.ctr:.2%} 낮음 → 광고문구·확장소재 점검"
    return rec


def recommend_all(perfs: list[KeywordPerformance], rules: BidRules = BidRules()) -> list[BidRecommendation]:
    return sorted((recommend(p, rules) for p in perfs), key=lambda r: (r.priority, -r.perf.cost))
