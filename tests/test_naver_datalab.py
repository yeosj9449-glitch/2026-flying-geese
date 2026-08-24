from flying_geese.stage2_blue_ocean.naver_datalab import NaverDatalabClient


def test_latest_ratio_by_keyword_normal_response():
    response = {
        "results": [
            {"title": "감홍사과", "data": [{"period": "2026-07-01", "ratio": 45.2}, {"period": "2026-08-01", "ratio": 52.7}]},
        ]
    }
    ratios = NaverDatalabClient.latest_ratio_by_keyword(response)
    assert ratios == {"감홍사과": 52.7}


def test_latest_ratio_by_keyword_does_not_crash_on_null_ratio():
    """네이버 데이터랩이 특정 구간에 ratio: null을 내려줘도 전체 파싱이
    죽지 않고 해당 그룹은 0.0으로 처리돼야 한다."""
    response = {
        "results": [
            {"title": "무응답품종", "data": [{"period": "2026-08-01", "ratio": None}]},
            {"title": "정상품종", "data": [{"period": "2026-08-01", "ratio": 30.0}]},
        ]
    }
    ratios = NaverDatalabClient.latest_ratio_by_keyword(response)
    assert ratios == {"무응답품종": 0.0, "정상품종": 30.0}


def test_latest_ratio_by_keyword_skips_group_with_no_data_points():
    response = {"results": [{"title": "데이터없음", "data": []}]}
    ratios = NaverDatalabClient.latest_ratio_by_keyword(response)
    assert ratios == {}
