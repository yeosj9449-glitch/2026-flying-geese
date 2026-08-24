from flying_geese.config import Settings
from flying_geese.models import Supplier
from flying_geese.stage3_supplier.risk_filter import evaluate_supplier, evaluate_suppliers, passing_suppliers


def make_settings() -> Settings:
    return Settings(
        min_supplier_fulfillment_rate=0.95,
        max_supplier_return_rate=0.03,
        max_supplier_avg_delivery_hours=30.0,
    )


def test_supplier_passes_when_within_thresholds():
    supplier = Supplier("S1", "우수농장", "경북", 0.98, 20, 0.01, True)
    evaluation = evaluate_supplier(supplier, make_settings())
    assert evaluation.passed is True
    assert evaluation.reasons == []


def test_supplier_fails_on_low_fulfillment_rate():
    supplier = Supplier("S2", "늦은농장", "전남", 0.90, 20, 0.01, False)
    evaluation = evaluate_supplier(supplier, make_settings())
    assert evaluation.passed is False
    assert any("이행률" in reason for reason in evaluation.reasons)


def test_supplier_fails_on_high_return_rate():
    supplier = Supplier("S3", "반품농장", "강원", 0.98, 20, 0.10, False)
    evaluation = evaluate_supplier(supplier, make_settings())
    assert evaluation.passed is False
    assert any("반품률" in reason for reason in evaluation.reasons)


def test_passing_suppliers_filters_and_sorts_by_trust_score():
    settings = make_settings()
    good = Supplier("S1", "우수농장", "경북", 0.99, 15, 0.005, True)
    bad = Supplier("S2", "위험농장", "전남", 0.80, 50, 0.10, False)
    evaluations = evaluate_suppliers([bad, good], settings)
    assert evaluations[0].supplier.supplier_id == "S1"
    assert passing_suppliers(evaluations) == [good]
