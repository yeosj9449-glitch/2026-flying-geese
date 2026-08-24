"""공급처 지표 로딩 및 신뢰 점수 산출."""
from __future__ import annotations

import json
from pathlib import Path

from flying_geese.models import Supplier


def load_suppliers(path: str | Path) -> list[Supplier]:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"공급처 데이터 파일을 찾을 수 없습니다: {file_path}")

    raw = json.loads(file_path.read_text(encoding="utf-8"))
    return [
        Supplier(
            supplier_id=item["supplier_id"],
            supplier_name=item["supplier_name"],
            region=item["region"],
            fulfillment_rate=item["fulfillment_rate"],
            avg_delivery_hours=item["avg_delivery_hours"],
            return_rate=item["return_rate"],
            has_e_tracking=item.get("has_e_tracking", False),
        )
        for item in raw
    ]


def trust_score(supplier: Supplier) -> float:
    """0~100 스케일의 신뢰 점수. 이행률/반품률/배송시간/전자송품장 가점을 종합한다."""
    score = 0.0
    score += supplier.fulfillment_rate * 50  # 최대 50점
    score += max(0.0, (1 - supplier.return_rate * 10)) * 30  # 최대 30점, 반품률 10%면 0점
    delivery_score = max(0.0, (48 - supplier.avg_delivery_hours) / 48) * 15  # 최대 15점
    score += delivery_score
    if supplier.has_e_tracking:
        score += 5  # 전자송품장 가점
    return round(min(score, 100.0), 2)
