"""블루오션 지수 (월간 검색량 / 경쟁 상품 수) + 검색 모멘텀 기반 틈새 상품 스코어링."""
from __future__ import annotations

from flying_geese.models import VarietyCandidate


def build_candidates(
    base_product: str,
    varieties: list[str],
    search_volumes: dict[str, int],
    competitor_counts: dict[str, int],
    search_trends: dict[str, float] | None = None,
) -> tuple[list[VarietyCandidate], list[str]]:
    """세부 품종별 스코어링 후보를 만든다.

    경쟁 상품 수 데이터가 없는 품종은 0으로 임의 대체하지 않는다 (0competitor로
    가정하면 블루오션 지수가 검색량 그대로 튀어올라, 데이터 누락 품종이 오히려
    1위로 오인될 수 있다). 대신 후보에서 제외하고 별도로 반환해 운영자가
    데이터 보강 대상으로 확인할 수 있게 한다.

    반환값: (스코어링 후보 목록, 경쟁상품 데이터 누락으로 제외된 품종 목록)
    """
    search_trends = search_trends or {}
    candidates: list[VarietyCandidate] = []
    missing_competitor_data: list[str] = []

    for variety in varieties:
        if variety not in competitor_counts:
            missing_competitor_data.append(variety)
            continue
        candidates.append(
            VarietyCandidate(
                base_product=base_product,
                variety_keyword=variety,
                monthly_search_volume=search_volumes.get(variety, 0),
                competitor_product_count=competitor_counts[variety],
                search_trend_ratio=search_trends.get(variety, 1.0),
            )
        )
    return candidates, missing_competitor_data


def rank_blue_ocean(
    candidates: list[VarietyCandidate],
    min_search_volume: int = 100,
    top_n: int | None = None,
) -> list[VarietyCandidate]:
    """검색 모멘텀 반영 스코어(trending_score) 내림차순 정렬.

    최소 검색량 미달 키워드는 노이즈로 제외한다.
    """
    filtered = [c for c in candidates if c.monthly_search_volume >= min_search_volume]
    ranked = sorted(filtered, key=lambda c: c.trending_score, reverse=True)
    return ranked[:top_n] if top_n else ranked
