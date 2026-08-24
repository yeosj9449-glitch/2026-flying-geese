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


def test_failed_supplier_never_ranks_above_passed_supplier_even_with_higher_trust_score():
    """배송시간만 근소하게 초과해 제외된 공급처가, 다른 지표가 우수하다는
    이유로 trust_score 단순 정렬 시 통과 공급처보다 위로 올라가는 것을 막는다."""
    settings = make_settings()
    borderline_pass = Supplier("S1", "턱걸이통과농장", "경북", 0.95, 29.9, 0.029, False)
    high_score_fail = Supplier(
        "S2", "배송시간초과농장", "전남", 0.99, 30.1, 0.001, True
    )

    evaluations = evaluate_suppliers([high_score_fail, borderline_pass], settings)

    # 실제로 제외 공급처의 trust_score가 더 높은지 전제를 확인한다.
    fail_eval = next(e for e in evaluations if e.supplier.supplier_id == "S2")
    pass_eval = next(e for e in evaluations if e.supplier.supplier_id == "S1")
    assert fail_eval.trust_score > pass_eval.trust_score
    assert fail_eval.passed is False

    # 그럼에도 통과 공급처가 항상 먼저 나와야 한다.
    assert [e.supplier.supplier_id for e in evaluations] == ["S1", "S2"]
