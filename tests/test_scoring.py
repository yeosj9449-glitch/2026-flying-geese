from flying_geese.models import VarietyCandidate
from flying_geese.stage2_blue_ocean.scoring import build_candidates, rank_blue_ocean


def test_blue_ocean_index_calculation():
    candidate = VarietyCandidate("고구마", "베니하르카 호박고구마", 4200, 45)
    assert round(candidate.blue_ocean_index, 1) == 93.3


def test_zero_competitors_returns_full_volume():
    candidate = VarietyCandidate("고구마", "희귀품종", 500, 0)
    assert candidate.blue_ocean_index == 500


def test_rank_blue_ocean_orders_descending_and_filters_low_volume():
    candidates = build_candidates(
        base_product="고구마",
        varieties=["베니하르카 호박고구마", "밤고구마", "노이즈품종"],
        search_volumes={"베니하르카 호박고구마": 4200, "밤고구마": 12000, "노이즈품종": 10},
        competitor_counts={"베니하르카 호박고구마": 45, "밤고구마": 1800, "노이즈품종": 1},
    )
    ranked = rank_blue_ocean(candidates, min_search_volume=100)
    assert [c.variety_keyword for c in ranked] == ["베니하르카 호박고구마", "밤고구마"]
