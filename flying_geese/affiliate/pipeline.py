"""키워드 → 쿠팡 파트너스 상품 검색 → 게시물 초안 생성.

키워드는 직접 지정하거나, 상품 선정(product_selection.py) 결과의 블루오션
상위 품종을 그대로 쓴다 - 제철 + 검색량 대비 경쟁이 적은 키워드는 어필리에이트
콘텐츠에서도 검색 노출을 얻기 쉬운 주제다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from flying_geese.affiliate.content_builder import build_post_draft, write_drafts
from flying_geese.affiliate.coupang_partners_api import AffiliateProduct

logger = logging.getLogger(__name__)

DEFAULT_DRAFT_DIR = Path(__file__).resolve().parent.parent.parent / "output" / "affiliate_drafts"


@dataclass
class DraftRunReport:
    draft_paths: list[Path] = field(default_factory=list)
    empty_keywords: list[str] = field(default_factory=list)
    failed_keywords: dict[str, str] = field(default_factory=dict)


def keywords_from_selection(report, top_n: int = 5) -> list[str]:
    return [c.variety_keyword for c in report.blue_ocean_ranking[:top_n]]


def run_affiliate_drafts(
    keywords: list[str],
    client,
    products_per_post: int = 5,
    output_dir: Path | None = None,
) -> DraftRunReport:
    """키워드 하나의 검색 실패가 나머지 키워드 초안 생성을 막지 않도록 한다."""
    report = DraftRunReport()
    drafts: dict[str, str] = {}
    for keyword in dict.fromkeys(keywords):
        try:
            products: list[AffiliateProduct] = client.search_products(keyword, limit=products_per_post)
        except Exception as exc:  # noqa: BLE001 - 키워드 단위로 격리
            logger.warning("'%s' 검색 실패: %s", keyword, exc)
            report.failed_keywords[keyword] = str(exc)
            continue
        if not products:
            report.empty_keywords.append(keyword)
            continue
        drafts[keyword] = build_post_draft(keyword, products)
    report.draft_paths = write_drafts(drafts, output_dir or DEFAULT_DRAFT_DIR)
    return report
