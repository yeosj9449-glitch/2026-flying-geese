"""계산 엔진이 스프레드시트와 같은 숫자를 내는지 검증한다.

fixtures/household_dashboard_expected.json은 샘플 워크북을 구성원 보기 4종으로 각각
LibreOffice에서 재계산해 읽은 값이다 (재계산 시점의 오늘 = 2026-10-12 - 다시 만들면 TODAY도 바꾼다).
"""

import json
from datetime import date
from pathlib import Path

import pytest

from household_finance.engine import compute, xround
from household_finance.model import load_workbook_dataset, sample_dataset
from household_finance.workbook import build_workbook

EXPECTED = json.loads((Path(__file__).parent / "fixtures" / "household_dashboard_expected.json").read_text(encoding="utf-8"))
TODAY = date(2026, 10, 12)
VIEWS = ["전체", "본인", "배우자", "공동"]


def close(a, b, tol=0.5):
    if a is None or b is None:
        return a in (None, "") and b in (None, "")
    return abs(a - b) <= tol


@pytest.fixture(scope="module")
def results():
    ds = sample_dataset()
    return {v: compute(ds, v, today=TODAY) for v in VIEWS}


@pytest.mark.parametrize("view", VIEWS)
def test_cards_match_spreadsheet(results, view):
    for got, exp in zip(results[view]["cards"], EXPECTED[view]["cards"]):
        assert got["label"] == exp["label"]
        tol = 0.5 if got["format"] == "won" else 1e-9
        assert close(got["value"], exp["value"], tol), (view, got["label"], got["value"], exp["value"])
        assert got["note"] == exp["sub"], (view, got["label"])
        assert got["status"] == exp["status"], (view, got["label"])


@pytest.mark.parametrize("view", VIEWS)
def test_alerts_match_spreadsheet(results, view):
    assert results[view]["alerts"] == EXPECTED[view]["alerts"]


@pytest.mark.parametrize("view", VIEWS)
def test_reports_match_spreadsheet(results, view):
    got, exp = results[view], EXPECTED[view]
    rows = got["pnl"]["rows"]
    assert got["pnl"]["months"] == exp["months"]
    for key, exp_key in [("income", "소득 합계"), ("consumption", "소비지출 합계"), ("invest", "투자 납입액 (투자+연금)"),
                         ("capital", "자본이동 합계")]:
        assert all(close(a, b) for a, b in zip(rows[key], exp["pnl"][exp_key])), key
    assert all(close(a, b, 1e-9) for a, b in zip(rows["saving_rate"], exp["pnl"]["저축률"]))
    for g, e in zip(got["balance"]["trend"], exp["trend"]):
        assert g["month"] == e["month"] and all(close(g[k], e[k]) for k in ("assets", "debt", "net", "invest", "cash"))
    for g, e in zip(got["budget"]["rows"], exp["budget"]):
        assert (g["category"], g["status"]) == (e["cat"], e["status"])
        assert close(g["period_budget"], e["budget"]) and close(g["actual"], e["actual"])
        assert all(close(g["by_member"][m], v) for m, v in zip(["본인", "배우자", "공동"], e["byMember"]))
    for g, e in zip(got["invest"]["allocation"], exp["alloc"]):
        assert g["status"] == e["status"] and close(g["value"], e["value"]) and close(g["current"], e["current"], 1e-9)
    for g, e in zip(got["goals"]["rows"], exp["goals"]):
        assert g["status"] == e["status"] and close(g["target"], e["target"]) and close(g["current"], e["current"])
        assert close(g["progress"], e["progress"], 1e-9) and close(g["plan"], e["plan"], 1e-9)
        assert close(g["monthly_needed"], e["monthly"], 1e-6)
    for g, e in zip(got["cashflow"]["rows"], exp["cashflow"]):
        assert g["month"] == e["month"] and close(g["net"], e["net"], 1e-6) and close(g["balance"], e["balance"], 1e-6)
    for g, e in zip(got["balance"]["members"], exp["members"]):
        assert all(close(g[k], e[k]) for k in ("assets", "debt", "net", "invest"))


def test_workbook_roundtrip_gives_same_dashboard(tmp_path):
    """스프레드시트 → 데이터셋으로 읽어도 같은 결과 (웹앱 이전 경로 검증)."""
    path = build_workbook(tmp_path / "sample.xlsx")
    loaded = load_workbook_dataset(path)
    for view in VIEWS:
        assert compute(loaded, view, today=TODAY)["cards"] == compute(sample_dataset(), view, today=TODAY)["cards"]


def test_excel_rounding():
    assert xround(2.5) == 3 and xround(-2.5) == -3 and xround(0.125, 2) == 0.13
    assert xround(23_013_420, -4) == 23_010_000


def test_unknown_view_rejected():
    with pytest.raises(ValueError):
        compute(sample_dataset(), "자녀")
