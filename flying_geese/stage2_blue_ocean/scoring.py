"""블루오션 지수 (월간 검색량 / 경쟁 상품 수) 기반 틈새 상품 스코어링."""
from __future__ import annotations

from flying_geese.models import VarietyCandidate


def build_candidates(
    base_product: str,
    varieties: list[str],
    search_volumes: dict[str, int],
    competitor_counts: dict[str, int],
) -> list[VarietyCandidate]:
    candidates = []
    for variety in varieties:
        candidates.append(
            VarietyCandidate(
                base_product=base_product,
                variety_keyword=variety,
                monthly_search_volume=search_volumes.get(variety, 0),
                competitor_product_count=competitor_counts.get(variety, 0),
            )
        )
    return candidates


def rank_blue_ocean(
    candidates: list[VarietyCandidate],
    min_search_volume: int = 100,
    top_n: int | None = None,
) -> list[VarietyCandidate]:
    """블루오션 지수 내림차순 정렬. 최소 검색량 미달 키워드는 노이즈로 제외."""
    filtered = [c for c in candidates if c.monthly_search_volume >= min_search_volume]
    ranked = sorted(filtered, key=lambda c: c.blue_ocean_index, reverse=True)
    return ranked[:top_n] if top_n else ranked
