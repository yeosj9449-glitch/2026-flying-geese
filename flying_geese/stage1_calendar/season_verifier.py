"""제철(출하 성수기) 시기를 데이터로 검증한다.

'제철 캘린더'는 경험 지식으로 작성한 참고값이라, 실제 소싱/판매 시점은 해마다
작황·기후에 따라 앞뒤로 움직인다. 이 모듈은 두 가지 월별 시계열로 시기를 판정한다.

  1) 공급 시계열: 도매시장 월별 반입량 (예: 가락시장 품목별 월별 반입량 통계)
     → 연간 물량 중 해당 월 비중이 평균(1/12)의 1.2배 이상이면 '출하 성수기'
     → 물량이 많을 때가 품질·가격이 안정되는 소싱 적기
  2) 수요 시계열: 네이버 데이터랩 월별 검색지수
     → 같은 기준으로 '검색 성수기'

판매 적기 = 출하 성수기 ∩ 검색 성수기, 사전예약 오픈 = 성수기 시작 직전 달.
결과를 제철 캘린더(seasonal_calendar.json)와 비교해 어긋나는 품목을 알려준다.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from flying_geese.models import SeasonalItem
from flying_geese.tabular import parse_float, parse_int, pick, read_csv_rows

PEAK_RATIO = 1.2  # 월 비중이 평균(1/12)의 몇 배 이상이면 성수기로 볼지
MIN_MONTHS_PER_YEAR = 10  # 연도별 비중 계산에 쓸 최소 월 수 (결측 많은 해는 제외)

MonthlySeries = dict[str, dict[tuple[int, int], float]]  # 품목 -> {(연도, 월): 값}


@dataclass
class SeasonCheck:
    item: str
    supply_share: dict[int, float]
    supply_peaks: list[int]
    search_peaks: list[int] = field(default_factory=list)
    calendar_peaks: list[int] = field(default_factory=list)
    sell_window: list[int] = field(default_factory=list)
    presale_month: int | None = None
    agreement: float | None = None  # 캘린더 vs 출하 성수기 일치도 (Jaccard)
    notes: list[str] = field(default_factory=list)


def load_monthly_series(path: str | Path) -> MonthlySeries:
    """CSV(품목, 연도, 월, 값) → 품목별 월별 시계열. 해석 불가 행은 건너뛴다."""
    series: MonthlySeries = defaultdict(dict)
    for row in read_csv_rows(path):
        item = pick(row, "품목")
        year = parse_int(pick(row, "연도"))
        month = parse_int(pick(row, "월"))
        value = parse_float(pick(row, "값", "반입량", "검색지수"))
        if not item or year is None or month is None or not 1 <= month <= 12 or value is None:
            continue
        series[item][(year, month)] = value
    return dict(series)


def monthly_share(points: dict[tuple[int, int], float]) -> dict[int, float]:
    """연도별 월 비중을 구해 평균한다 (연도 간 물량 규모 차이를 제거)."""
    by_year: dict[int, dict[int, float]] = defaultdict(dict)
    for (year, month), value in points.items():
        by_year[year][month] = value
    usable = [months for months in by_year.values() if len(months) >= MIN_MONTHS_PER_YEAR]
    if not usable:
        usable = list(by_year.values())

    shares: dict[int, list[float]] = defaultdict(list)
    for months in usable:
        total = sum(months.values())
        if total <= 0:
            continue
        for month in range(1, 13):
            shares[month].append(months.get(month, 0.0) / total)
    return {m: (sum(v) / len(v) if v else 0.0) for m, v in ((m, shares.get(m, [])) for m in range(1, 13))}


def peak_months(share: dict[int, float], ratio: float = PEAK_RATIO) -> list[int]:
    threshold = ratio / 12
    return [m for m in range(1, 13) if share.get(m, 0.0) >= threshold]


def contiguous_blocks(months: list[int]) -> list[list[int]]:
    """[11, 12, 1, 2] 처럼 해를 넘기는 구간도 하나의 블록으로 묶는다."""
    month_set = set(months)
    if len(month_set) == 12:
        return [list(range(1, 13))]
    blocks: list[list[int]] = []
    for m in range(1, 13):
        prev = 12 if m == 1 else m - 1
        if m in month_set and prev not in month_set:
            block = [m]
            nxt = m % 12 + 1
            while nxt in month_set:
                block.append(nxt)
                nxt = nxt % 12 + 1
            blocks.append(block)
    return blocks


def presale_month_for(peaks: list[int], share: dict[int, float]) -> int | None:
    """물량이 가장 큰 성수기 블록이 시작되기 직전 달."""
    blocks = contiguous_blocks(peaks)
    if not blocks:
        return None
    main = max(blocks, key=lambda b: sum(share.get(m, 0.0) for m in b))
    return 12 if main[0] == 1 else main[0] - 1


def calendar_peaks_by_category(calendar: list[SeasonalItem]) -> dict[str, list[int]]:
    grouped: dict[str, set[int]] = defaultdict(set)
    for item in calendar:
        grouped[item.category].update(item.peak_months)
    return {k: sorted(v) for k, v in grouped.items()}


def verify_seasons(
    supply: MonthlySeries,
    search: MonthlySeries | None = None,
    calendar: list[SeasonalItem] | None = None,
    ratio: float = PEAK_RATIO,
) -> list[SeasonCheck]:
    calendar_map = calendar_peaks_by_category(calendar or [])
    results: list[SeasonCheck] = []
    for item, points in sorted(supply.items()):
        share = monthly_share(points)
        supply_peaks = peak_months(share, ratio)
        check = SeasonCheck(item=item, supply_share=share, supply_peaks=supply_peaks)

        if search and item in search:
            check.search_peaks = peak_months(monthly_share(search[item]), ratio)
            check.sell_window = [m for m in supply_peaks if m in check.search_peaks]
            if not check.sell_window:
                check.notes.append("출하·검색 성수기가 겹치지 않음 - 검색이 앞서면 사전예약, 늦으면 재고 소진 주의")
        else:
            check.sell_window = list(supply_peaks)
        if check.search_peaks:
            early = [m for m in check.search_peaks if m not in supply_peaks]
            if early:
                check.notes.append(f"출하보다 검색이 먼저/더 길게 큼: {early}월 → 사전예약·콘텐츠 선행")
        check.presale_month = presale_month_for(supply_peaks, share)

        if item in calendar_map:
            check.calendar_peaks = calendar_map[item]
            cal, data = set(check.calendar_peaks), set(supply_peaks)
            union = cal | data
            check.agreement = round(len(cal & data) / len(union), 2) if union else None
            if data - cal:
                check.notes.append(f"캘린더에 없는 출하 성수기: {sorted(data - cal)}월 → 캘린더 보강 검토")
            if cal - data:
                check.notes.append(f"캘린더엔 제철이나 출하 비중 낮음: {sorted(cal - data)}월 → 소싱 시기 재확인")
        elif calendar is not None:
            check.notes.append("제철 캘린더 미등록 품목 - 추가 권장")
        results.append(check)
    return results
