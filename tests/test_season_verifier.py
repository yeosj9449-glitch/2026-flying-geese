from flying_geese.models import SeasonalItem
from flying_geese.stage1_calendar.season_verifier import (
    contiguous_blocks,
    monthly_share,
    peak_months,
    presale_month_for,
    verify_seasons,
)


def _series(values, years=(2024, 2025)):
    return {(y, m): v for y in years for m, v in enumerate(values, start=1)}


STRAWBERRY = [18, 17, 16, 11, 5, 1, 0, 0, 0, 1, 4, 14]


def test_peak_months_across_year_boundary():
    share = monthly_share(_series(STRAWBERRY))
    peaks = peak_months(share)
    assert peaks == [1, 2, 3, 4, 12]
    assert contiguous_blocks(peaks) == [[12, 1, 2, 3, 4]]  # 해를 넘기는 구간은 하나의 블록
    assert presale_month_for(peaks, share) == 11


def test_monthly_share_normalizes_year_scale():
    small = {(2024, m): v for m, v in enumerate(STRAWBERRY, start=1)}
    big = {(2025, m): v * 10 for m, v in enumerate(STRAWBERRY, start=1)}
    share = monthly_share({**small, **big})
    assert abs(sum(share.values()) - 1.0) < 1e-9
    assert abs(share[1] - STRAWBERRY[0] / sum(STRAWBERRY)) < 1e-9


def test_incomplete_year_is_ignored_when_complete_year_exists():
    points = _series(STRAWBERRY, years=(2025,))
    points[(2026, 7)] = 1000  # 한 달치만 있는 해
    assert peak_months(monthly_share(points)) == [1, 2, 3, 4, 12]


def test_verify_compares_with_calendar_and_search():
    calendar = [SeasonalItem("딸기", "설향딸기", "과일", [12, 1, 2, 3, 4])]
    search = {"딸기": _series([17, 14, 12, 8, 4, 2, 1, 1, 2, 4, 12, 20])}
    check = verify_seasons({"딸기": _series(STRAWBERRY), "블루베리": _series([0, 0, 0, 0, 3, 25, 38, 22, 8, 2, 1, 1])}, search, calendar)
    strawberry, blueberry = sorted(check, key=lambda c: c.item != "딸기")
    assert strawberry.agreement == 1.0
    assert 11 in strawberry.search_peaks and any("사전예약" in n for n in strawberry.notes)
    assert strawberry.sell_window == [1, 2, 3, 12]
    assert blueberry.supply_peaks == [6, 7, 8] and any("미등록" in n for n in blueberry.notes)
