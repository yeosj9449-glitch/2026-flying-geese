import io
from datetime import date

import pytest
from fastapi.testclient import TestClient

from household_finance.engine import compute
from household_finance.model import load_workbook_dataset, sample_dataset
from household_finance.webapp.app import create_app
from household_finance.workbook import build_workbook

TODAY = date(2026, 10, 11)
USERS = [{"username": "jiwoo", "password": "password-1", "member": "본인"},
         {"username": "minseo", "password": "password-2", "member": "배우자"}]


@pytest.fixture
def client(tmp_path):
    c = TestClient(create_app(tmp_path / "home.db", today=TODAY))
    assert c.get("/api/status").json() == {"setup_needed": True, "has_data": False, "setup_code_required": False}
    assert c.post("/api/setup", json={"users": USERS, "start": "sample"}).status_code == 200
    return c


def test_setup_logs_in_and_only_runs_once(client):
    assert client.get("/api/me").json()["username"] == "jiwoo"
    assert client.post("/api/setup", json={"users": USERS, "start": "blank"}).status_code == 409


def test_requires_login(tmp_path, client):
    anon = TestClient(client.app)
    for path in ["/api/dashboard", "/api/transactions", "/api/meta", "/api/export.xlsx"]:
        assert anon.get(path).status_code == 401
    assert anon.post("/api/login", json={"username": "jiwoo", "password": "wrong-pass"}).status_code == 401
    assert anon.post("/api/login", json={"username": "minseo", "password": "password-2"}).status_code == 200
    assert anon.get("/api/me").json()["member"] == "배우자"
    anon.post("/api/logout")
    assert anon.get("/api/me").status_code == 401


def test_dashboard_matches_engine(client):
    for view in ["전체", "공동"]:
        got = client.get("/api/dashboard", params={"view": view}).json()
        assert got["cards"] == compute(sample_dataset(), view, today=TODAY)["cards"]
        assert got["alerts"] == compute(sample_dataset(), view, today=TODAY)["alerts"]
    assert client.get("/api/dashboard", params={"view": "자녀"}).status_code == 422


def test_classify_and_rule_reclassifies_uncategorized(client):
    assert client.post("/api/transactions", json={"day": "2026-09-30", "desc": "x", "amount": 1,
                                                  "category": "식비", "member": "자녀"}).status_code == 422
    tx = client.post("/api/transactions", json={"day": "2026-09-30", "desc": "동네꽃집 성수", "amount": 25000,
                                                "category": "여가", "member": "본인"}).json()["id"]
    assert client.patch(f"/api/transactions/{tx}", json={"category": "없는카테고리"}).status_code == 422
    assert client.patch(f"/api/transactions/{tx}", json={"category": "쇼핑"}).status_code == 200
    rows = client.get("/api/transactions", params={"q": "꽃집"}).json()
    assert [(r["category"], r["group"]) for r in rows] == [("쇼핑", "변동비")]
    assert client.delete(f"/api/transactions/{tx}").status_code == 200
    assert client.get("/api/transactions", params={"q": "꽃집"}).json() == []


def test_statement_upload_dry_run_then_import_then_duplicates(client):
    csv = "이용일자,이용가맹점,이용금액\n2026.09.29,배달의민족,\"32,000\"\n2026.09.30,동네꽃집,\"25,000\"\n".encode("cp949")
    send = lambda dry: client.post("/api/import/statement", data={"member": "배우자", "payment": "현대카드", "dry_run": str(dry).lower()},
                                   files={"file": ("card.csv", io.BytesIO(csv), "text/csv")}).json()
    preview = send(True)
    assert [t["category"] for t in preview["added"]] == ["외식", "미분류"] and preview["uncategorized"] == 1
    assert client.get("/api/transactions", params={"q": "꽃집"}).json() == []
    assert len(send(False)["added"]) == 2
    again = send(False)
    assert again["added"] == [] and again["duplicates"] == 2
    # 규칙을 만들면 미분류였던 거래가 바로 분류된다
    assert client.post("/api/rules", json={"keyword": "꽃집", "category": "생활용품"}).json() == {"reclassified": 1}
    assert client.get("/api/transactions", params={"q": "꽃집"}).json()[0]["category"] == "생활용품"
    dash = client.get("/api/dashboard").json()
    assert not any("미분류" in a for a in dash["alerts"])


def test_upload_rejects_wrong_type(client):
    r = client.post("/api/import/statement", data={"member": "본인"}, files={"file": ("a.pdf", io.BytesIO(b"x"), "application/pdf")})
    assert r.status_code == 422


def test_close_month_copies_balances_and_moves_base_month(client):
    r = client.post("/api/close-month", json={"month": "2026-10"}).json()
    assert r == {"month": "2026-10", "copied": 17}
    snap = client.get("/api/snapshots/2026-10").json()["rows"]
    assert all(row["amount"] == row["previous"] for row in snap)
    assert client.put("/api/snapshots/2026-10", json={"amounts": {"A04": 16_000_000}}).json() == {"saved": 1}
    assert client.put("/api/snapshots/2026-10", json={"amounts": {"ZZZ": 1}}).status_code == 422
    meta = client.get("/api/meta").json()
    assert meta["base_month"] == "2026-10"
    dash = client.get("/api/dashboard").json()
    assert dash["base_month"] == "2026-10" and dash["balance"]["current"]["emergency"] > 0


def test_settings_and_budget_change_the_dashboard(client):
    assert client.put("/api/settings", json={"invest_targets": {"본인": 600_000}}).status_code == 200
    me_view = client.get("/api/dashboard", params={"view": "본인"}).json()
    invest_card = next(c for c in me_view["cards"] if c["kpi"] == "invest_paid")
    assert invest_card["status"] == "✅ 달성"            # 9월 본인 납입 90만 ≥ 목표 60만
    assert client.put("/api/settings", json={"invest_targets": {"자녀": 1}}).status_code == 422
    assert client.put("/api/budgets/외식", json={"basis": "월", "amount": 600_000}).status_code == 200
    budget = client.get("/api/dashboard").json()["budget"]
    assert next(r for r in budget["rows"] if r["category"] == "외식")["status"] == "✅ 양호"


def test_excel_export_and_import_roundtrip(client, tmp_path):
    r = client.get("/api/export.xlsx")
    assert r.status_code == 200 and r.content[:2] == b"PK"
    path = tmp_path / "export.xlsx"
    path.write_bytes(r.content)
    exported = load_workbook_dataset(path)
    assert len(exported.transactions) == len(sample_dataset().transactions)
    assert compute(exported, today=TODAY)["cards"] == compute(sample_dataset(), today=TODAY)["cards"]

    blank = build_workbook(tmp_path / "blank.xlsx", sample=False, base_month="2026-09")
    up = client.post("/api/import/workbook", files={"file": ("blank.xlsx", blank.read_bytes(), "application/octet-stream")}).json()
    assert up == {"transactions": 0, "accounts": 0, "base_month": "2026-09"}
    assert client.get("/api/me").status_code == 200         # 계정은 유지
    assert client.get("/api/dashboard").json()["alerts"][0].startswith("⚠ 투자 납입")


def test_static_app_is_served(client):
    assert "우리집 주식회사" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200
