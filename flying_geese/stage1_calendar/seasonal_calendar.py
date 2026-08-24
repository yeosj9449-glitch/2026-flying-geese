"""월별 제철 캘린더 로딩 및 조회 로직.

aT/스마트 APC 등에서 파악한 대표 품목-세부 품종별 제철 구간(peak_months)을
로컬 데이터셋(JSON)으로 관리한다. 실 운영 시에는 aT 제철정보 API나 산지
출하 통계로 주기적으로 갱신하는 것을 권장한다.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from flying_geese.models import SeasonalItem


def load_seasonal_calendar(path: str | Path) -> list[SeasonalItem]:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"제철 캘린더 데이터 파일을 찾을 수 없습니다: {file_path}")

    raw = json.loads(file_path.read_text(encoding="utf-8"))
    return [
        SeasonalItem(
            category=item["category"],
            variety_keyword=item["variety"],
            product_type=item.get("type", "농산"),
            peak_months=item["peak_months"],
        )
        for item in raw
    ]


def items_for_month(items: list[SeasonalItem], month: int) -> list[SeasonalItem]:
    """해당 월이 제철 구간에 포함되는 품종만 반환한다."""
    return [item for item in items if item.is_in_season(month)]


def upcoming_items(
    items: list[SeasonalItem], current_month: int, lookahead_months: int = 1
) -> list[SeasonalItem]:
    """다음 N개월 내 제철이 시작되지만 이번 달은 아직 제철이 아닌 품종을 반환한다.

    사전예약/입고 준비 마케팅에 활용한다 (예: 이번 달이 8월이면 9월에 제철이
    시작되는 품종을 미리 알려준다).
    """
    this_month_items = {(i.category, i.variety_keyword) for i in items_for_month(items, current_month)}
    result: list[SeasonalItem] = []
    seen: set[tuple[str, str]] = set()
    for offset in range(1, lookahead_months + 1):
        target_month = (current_month - 1 + offset) % 12 + 1
        for item in items_for_month(items, target_month):
            key = (item.category, item.variety_keyword)
            if key in this_month_items or key in seen:
                continue
            seen.add(key)
            result.append(item)
    return result


def category_variety_map(items: list[SeasonalItem]) -> dict[str, list[str]]:
    """대표 품목(category) -> 이 시기 추천 세부 품종 목록으로 재구성한다."""
    grouped: dict[str, list[str]] = defaultdict(list)
    for item in items:
        grouped[item.category].append(item.variety_keyword)
    return dict(grouped)
