from flying_geese.pipeline import DEFAULT_DATA_DIR, run_demo_pipeline


def test_run_demo_pipeline_end_to_end(tmp_path):
    # target_month=8로 고정해 어느 시점에 테스트를 돌려도 제철 캘린더 매칭이 동일하게 나오도록 한다.
    report = run_demo_pipeline(data_dir=DEFAULT_DATA_DIR, output_dir=tmp_path, target_month=8)

    assert report.target_month == 8

    product_names = {r.product_name for r in report.passing_price_items}
    assert "배추" not in product_names  # YoY 40% 폭등으로 제외되어야 함
    assert "사과" in product_names
    assert "고구마" in product_names

    assert report.seasonal_matched_categories == {"사과", "고구마"}

    # 8월 제철 캘린더에 매칭되는 품종(홍로사과, 베니하르카 호박고구마)만 채점 대상이 되어야 한다.
    ranked_varieties = [c.variety_keyword for c in report.blue_ocean_ranking]
    assert ranked_varieties == ["베니하르카 호박고구마", "홍로사과"]
    assert "감홍사과" not in ranked_varieties  # 9월이 제철이므로 8월 기준에서는 제외
    assert report.blue_ocean_missing_competitor_data == []

    # 다음 달(9월) 제철 예정 미리보기에 감홍사과가 포함되어야 한다.
    upcoming_varieties = {i.variety_keyword for i in report.upcoming_next_month}
    assert "감홍사과" in upcoming_varieties

    passed_ids = {e.supplier.supplier_id for e in report.supplier_evaluations if e.passed}
    assert passed_ids == {"S001", "S005"}

    assert report.simulation.required_monthly_orders > 0
    assert report.cashflow.working_capital_required > 0

    assert report.purchase_order_path.exists()
    assert "ORD-0004" in report.missing_tracking_order_ids
    assert len(report.dispatched_orders) == 3
