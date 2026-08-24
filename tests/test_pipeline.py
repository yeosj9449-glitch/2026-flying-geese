from flying_geese.pipeline import DEFAULT_DATA_DIR, run_demo_pipeline


def test_run_demo_pipeline_end_to_end(tmp_path):
    report = run_demo_pipeline(data_dir=DEFAULT_DATA_DIR, output_dir=tmp_path)

    product_names = {r.product_name for r in report.passing_price_items}
    assert "배추" not in product_names  # YoY 40% 폭등으로 제외되어야 함
    assert "사과" in product_names
    assert "고구마" in product_names

    assert report.blue_ocean_ranking[0].variety_keyword == "베니하르카 호박고구마"

    passed_ids = {e.supplier.supplier_id for e in report.supplier_evaluations if e.passed}
    assert passed_ids == {"S001", "S005"}

    assert report.simulation.required_monthly_orders > 0
    assert report.cashflow.working_capital_required > 0

    assert report.purchase_order_path.exists()
    assert "ORD-0004" in report.missing_tracking_order_ids
    assert len(report.dispatched_orders) == 3
