"""쿠팡/스마트스토어 경쟁 상품 수 조회.

쿠팡/스마트스토어는 키워드별 '상품 등록 수'를 제공하는 공식 오픈API가 없으므로,
운영자가 스크래핑 파이프라인 등으로 채운 데이터 소스를 주입받는 형태로 설계한다.
`MarketplaceRankSource` 프로토콜을 구현한 어댑터를 갈아끼우면 된다.
"""
from __future__ import annotations

from typing import Protocol


class MarketplaceRankSource(Protocol):
    def competitor_count(self, keyword: str) -> int:
        """해당 키워드로 검색되는 경쟁 상품(등록 상품) 수를 반환한다."""
        ...


class StaticMarketplaceRankSource:
    """운영자가 미리 조사/수집한 키워드별 경쟁 상품 수 테이블 기반 어댑터."""

    def __init__(self, counts: dict[str, int], default_count: int = 999):
        self._counts = counts
        self._default_count = default_count

    def competitor_count(self, keyword: str) -> int:
        return self._counts.get(keyword, self._default_count)


def bulk_competitor_counts(
    source: MarketplaceRankSource, keywords: list[str]
) -> dict[str, int]:
    return {kw: source.competitor_count(kw) for kw in keywords}
