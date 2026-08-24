from flying_geese.models import VarietyCandidate
from flying_geese.stage2_blue_ocean.scoring import build_candidates, rank_blue_ocean


def test_blue_ocean_index_calculation():
    candidate = VarietyCandidate("고구마", "베니하르카 호박고구마", 4200, 45)
    assert round(candidate.blue_ocean_index, 1) == 93.3


def test_zero_competitors_returns_full_volume():
    candidate = VarietyCandidate("고구마", "희귀품종", 500, 0)
    assert candidate.blue_ocean_index == 500


def test_rank_blue_ocean_orders_descending_and_filters_low_volume():
    candidates, missing = build_candidates(
        base_product="고구마",
        varieties=["베니하르카 호박고구마", "밤고구마", "노이즈품종"],
        search_volumes={"베니하르카 호박고구마": 4200, "밤고구마": 12000, "노이즈품종": 10},
        competitor_counts={"베니하르카 호박고구마": 45, "밤고구마": 1800, "노이즈품종": 1},
    )
    assert missing == []
    ranked = rank_blue_ocean(candidates, min_search_volume=100)
    assert [c.variety_keyword for c in ranked] == ["베니하르카 호박고구마", "밤고구마"]


def test_build_candidates_excludes_varieties_missing_competitor_data():
    """경쟁상품 수 데이터가 없는 품종을 0으로 임의 대체하면 블루오션 지수가
    검색량 그대로 튀어올라 데이터 누락 품종이 1위로 오인될 수 있다. 대신
    후보에서 제외되고 별도 목록으로 보고되어야 한다."""
    candidates, missing = build_candidates(
        base_product="사과",
        varieties=["감홍사과", "데이터없는품종"],
        search_volumes={"감홍사과": 8200, "데이터없는품종": 999999},
        competitor_counts={"감홍사과": 120},
    )
    assert [c.variety_keyword for c in candidates] == ["감홍사과"]
    assert missing == ["데이터없는품종"]


def test_trending_score_favors_rising_keyword_over_higher_raw_index():
    candidates, _ = build_candidates(
        base_product="배추",
        varieties=["안정형", "상승형"],
        search_volumes={"안정형": 10000, "상승형": 9000},
        competitor_counts={"안정형": 100, "상승형": 100},
        search_trends={"안정형": 1.0, "상승형": 1.5},
    )
    ranked = rank_blue_ocean(candidates)
    # 원시 블루오션 지수는 안정형(100)이 상승형(90)보다 높지만,
    # 검색 모멘텀을 반영하면 상승형(135)이 앞서야 한다.
    assert [c.variety_keyword for c in ranked] == ["상승형", "안정형"]
