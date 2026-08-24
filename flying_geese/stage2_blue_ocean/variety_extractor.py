"""대표 품목 → 세부 품종 키워드 확장.

예: '사과' -> ['감홍사과', '부사사과', '홍로사과'], '고구마' -> ['베니하르카 호박고구마', ...]
매핑 테이블은 JSON 파일로 관리하여 운영자가 쉽게 갱신할 수 있게 한다.
"""
from __future__ import annotations

import json
from pathlib import Path


def load_variety_map(path: str | Path) -> dict[str, list[str]]:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"품종 매핑 파일을 찾을 수 없습니다: {file_path}")
    return json.loads(file_path.read_text(encoding="utf-8"))


def expand_varieties(base_products: list[str], variety_map: dict[str, list[str]]) -> dict[str, list[str]]:
    """대표 품목 목록에 대해 세부 품종 키워드를 조회한다. 매핑이 없으면 원 품목만 반환."""
    return {product: variety_map.get(product, [product]) for product in base_products}
