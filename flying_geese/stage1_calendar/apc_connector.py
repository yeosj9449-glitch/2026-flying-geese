"""거점 스마트 APC(농산물산지유통센터) 100개소 우수 출하 품목 연동.

공식 실시간 API가 없으므로, 운영자가 주기적으로 정리한 로컬 데이터셋(JSON)을
로드하는 방식으로 구현한다. 데이터 포맷은 data/sample/apc_sites.json 참고.
"""
from __future__ import annotations

import json
from pathlib import Path

from flying_geese.models import ApcSite


def load_apc_sites(path: str | Path) -> list[ApcSite]:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"APC 데이터 파일을 찾을 수 없습니다: {file_path}")

    raw = json.loads(file_path.read_text(encoding="utf-8"))
    return [
        ApcSite(
            apc_id=item["apc_id"],
            apc_name=item["apc_name"],
            region=item["region"],
            top_products=item.get("top_products", []),
            is_smart_apc=item.get("is_smart_apc", True),
        )
        for item in raw
    ]


def products_with_apc_priority(sites: list[ApcSite]) -> set[str]:
    """스마트 APC에서 우수 출하 품목으로 등록된 품목명 집합을 반환한다."""
    products: set[str] = set()
    for site in sites:
        if site.is_smart_apc:
            products.update(site.top_products)
    return products
