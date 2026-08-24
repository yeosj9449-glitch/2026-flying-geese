from flying_geese.models import SeasonalItem
from flying_geese.stage1_calendar.seasonal_calendar import (
    category_variety_map,
    items_for_month,
    upcoming_items,
)

SAMPLE_ITEMS = [
    SeasonalItem("사과", "홍로사과", "과일", [8, 9]),
    SeasonalItem("사과", "감홍사과", "과일", [9, 10]),
    SeasonalItem("고구마", "베니하르카 호박고구마", "농산", [8, 9, 10]),
    SeasonalItem("배", "신고배", "과일", [9, 10]),
]


def test_items_for_month_filters_by_peak_month():
    august_items = items_for_month(SAMPLE_ITEMS, 8)
    assert {i.variety_keyword for i in august_items} == {"홍로사과", "베니하르카 호박고구마"}


def test_upcoming_items_excludes_items_already_in_season():
    upcoming = upcoming_items(SAMPLE_ITEMS, current_month=8, lookahead_months=1)
    names = {i.variety_keyword for i in upcoming}
    # 감홍사과, 신고배는 9월에 새로 시작하므로 포함
    assert names == {"감홍사과", "신고배"}
    # 베니하르카 호박고구마는 8월에도 이미 제철이므로 미리보기에서 제외
    assert "베니하르카 호박고구마" not in names


def test_upcoming_items_wraps_around_year_end():
    december_item = SeasonalItem("굴", "통영 생굴", "수산", [12, 1, 2])
    upcoming = upcoming_items([december_item], current_month=12, lookahead_months=1)
    assert upcoming == []  # 1월에도 이미 제철이므로 신규 미리보기 없음

    november_upcoming = upcoming_items([december_item], current_month=11, lookahead_months=1)
    assert [i.variety_keyword for i in november_upcoming] == ["통영 생굴"]


def test_category_variety_map_groups_by_category():
    # 9월에는 홍로사과(8~9월)와 감홍사과(9~10월)가 모두 제철에 걸쳐 있다.
    grouped = category_variety_map(items_for_month(SAMPLE_ITEMS, 9))
    assert grouped == {
        "사과": ["홍로사과", "감홍사과"],
        "고구마": ["베니하르카 호박고구마"],
        "배": ["신고배"],
    }
