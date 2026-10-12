import io
from datetime import date

import pytest
from fastapi.testclient import TestClient

from household_finance import prices
from household_finance.webapp.app import create_app

TODAY = date(2026, 10, 12)
USERS = [{"username": "jiwoo", "password": "password-1", "member": "본인"}]


# ---------------------------------------------------------------- 시세
def test_krx_code():
    assert prices.krx_code("KRX:005930") == "005930"
    assert prices.krx_code("360750") == "360750"
    assert prices.krx_code("krx:0080g0") == "0080G0"     # 신규 상장 ETF의 영숫자 코드
    assert prices.krx_code("") is None and prices.krx_code("NASDAQ:QQQM") is None


def test_parse_naver_both_shapes():
    assert prices.parse_naver({"stockName": "삼성전자", "closePrice": "71,500"}) == 71500
    assert prices.parse_naver({"datas": [{"itemCode": "005930", "closePrice": "72,100"}]}) == 72100
    with pytest.raises(ValueError):
        prices.parse_naver({"message": "not found"})


def test_refresh_fetches_each_code_once_and_isolates_failures():
    calls = []

    def fake(code):
        calls.append(code)
        if code == "148070":
            raise TimeoutError("timed out")
        return {"360750": 22000.0, "005930": 70000.0}[code]

    holdings = [{"id": 1, "name": "TIGER S&P500", "code": "KRX:360750", "price": 21300},
                {"id": 2, "name": "TIGER S&P500", "code": "KRX:360750", "price": 21300},
                {"id": 3, "name": "국고채10년", "code": "KRX:148070", "price": 111000},
                {"id": 4, "name": "정기예금", "code": "", "price": 1},
                {"id": 5, "name": "삼성전자", "code": "005930", "price": 71500}]
    r = prices.refresh(holdings, fake)
    assert sorted(calls) == ["005930", "148070", "360750"]
    assert [(x["id"], x["new"]) for x in r["updated"]] == [(1, 22000.0), (2, 22000.0), (5, 70000.0)]
    assert [x["id"] for x in r["failed"]] == [3] and "연결할 수 없음" in r["failed"][0]["reason"]
    assert [x["id"] for x in r["skipped"]] == [4]


def test_price_csv_matches_by_code_then_name():
    table = prices.parse_price_csv('시세코드,현재가\nKRX:005930,"70,900"\nTDF2045,15800\n')
    holdings = [{"id": 1, "name": "삼성전자", "code": "005930", "price": 1}, {"id": 2, "name": "TDF2045", "code": "", "price": 1},
                {"id": 3, "name": "정기예금", "code": "", "price": 1}]
    r = prices.match_prices(holdings, table)
    assert [(x["id"], x["new"]) for x in r["updated"]] == [(1, 70900.0), (2, 15800.0)]
    with pytest.raises(ValueError):
        prices.parse_price_csv("a,b\n1,2\n")


# ---------------------------------------------------------------- 편집 API
@pytest.fixture
def client(tmp_path):
    def fake(code):   # 삼성전자만 조회되고 나머지는 네트워크가 막힌 상황
        if code == "005930":
            return 80000.0
        raise ConnectionError("blocked")

    c = TestClient(create_app(tmp_path / "home.db", today=TODAY, price_fetcher=fake))
    assert c.post("/api/setup", json={"users": USERS, "start": "sample"}).status_code == 200
    return c


def test_account_crud_and_delete_guard(client):
    acc = {"id": "A07", "name": "청약통장(자녀)", "institution": "국민은행", "type": "현금성", "owner": "공동", "liquidity": "장기"}
    assert client.post("/api/entities/accounts", json=acc).json() == {"id": "A07"}
    assert client.post("/api/entities/accounts", json=acc).status_code == 409                     # 같은 ID
    assert client.post("/api/entities/accounts", json={**acc, "id": "A08", "type": "주식"}).status_code == 422
    assert client.put("/api/entities/accounts/A07", json={**acc, "memo": "자녀 명의"}).status_code == 200
    assert client.put("/api/entities/accounts/A07", json={**acc, "id": "A09"}).status_code == 422  # ID 변경 불가
    assert any(a["id"] == "A07" for a in client.get("/api/meta").json()["accounts"])
    blocked = client.delete("/api/entities/accounts/A01")                                          # 잔액 기록이 있음
    assert blocked.status_code == 409 and "잔액 기록" in blocked.json()["detail"]
    assert client.delete("/api/entities/accounts/A07").status_code == 200


def test_event_and_insurance_edits_change_alerts(client):
    before = client.get("/api/dashboard").json()
    assert before["insurance"]["gaps"] == 2
    policies = client.get("/api/entities/insurances").json()
    spouse = next(p for p in policies if p["insured"] == "배우자")
    spouse["coverages"] = {**spouse["coverages"], "사망": 100_000_000, "배상책임": 100_000_000}
    pid = spouse.pop("id")
    assert client.put(f"/api/entities/insurances/{pid}", json=spouse).status_code == 200
    assert client.post("/api/entities/events", json={"day": "2026-10-20", "desc": "전세 재계약 상담", "kind": "알림", "member": "공동"}).status_code == 200
    after = client.get("/api/dashboard").json()
    assert after["insurance"]["gaps"] == 0
    assert not any("보장 공백" in a for a in after["alerts"])
    assert any("전세 재계약 상담 D-8" in a for a in after["alerts"])


def test_goal_validation_and_auto_target(client):
    goal = {"name": "가족 세계여행", "owner": "공동", "target": None, "start": "2026-01-01", "end": "2028-12-31", "accounts": ["A06"]}
    gid = client.post("/api/entities/goals", json=goal).json()["id"]
    row = next(g for g in client.get("/api/dashboard").json()["goals"]["rows"] if g["name"] == "가족 세계여행")
    assert row["auto_target"] and row["target"] > 0
    assert client.post("/api/entities/goals", json={**goal, "end": "2025-01-01"}).status_code == 422
    assert client.post("/api/entities/goals", json={**goal, "accounts": ["ZZ"]}).status_code == 422
    assert client.delete(f"/api/entities/goals/{gid}").status_code == 200


def test_debt_must_point_to_liability_account(client):
    debt = {"name": "자동차 할부", "account_id": "A01", "rate": 0.059, "maturity": "2028-01-31", "method": "원리금균등", "payment": 450000}
    assert client.post("/api/entities/debts", json=debt).status_code == 422
    assert client.post("/api/entities/debts", json={**debt, "account_id": "L03"}).status_code == 200


def test_allocation_must_cover_all_classes_and_sum_to_100(client):
    good = {"국내주식": 0.25, "해외주식": 0.40, "채권": 0.20, "현금성": 0.10, "대체투자": 0.05}
    assert client.put("/api/allocation", json={"targets": {**good, "채권": 0.30}}).status_code == 422
    assert client.put("/api/allocation", json={"targets": {"국내주식": 1.0}}).status_code == 422
    assert client.put("/api/allocation", json={"targets": good}).status_code == 200
    alloc = client.get("/api/dashboard").json()["invest"]["allocation"]
    assert next(a for a in alloc if a["asset_class"] == "국내주식")["target"] == 0.25


def test_price_refresh_updates_only_what_it_could_fetch(client):
    r = client.post("/api/prices/refresh", json={"dry_run": True}).json()
    assert {x["name"] for x in r["updated"]} == {"삼성전자"} and r["failed"]
    holdings = {h["name"]: h for h in client.get("/api/entities/holdings").json()}
    assert holdings["삼성전자"]["price"] == 71500                      # 미리보기는 저장하지 않음
    client.post("/api/prices/refresh", json={"dry_run": False})
    holdings = {h["name"]: h for h in client.get("/api/entities/holdings").json()}
    assert holdings["삼성전자"]["price"] == 80000 and holdings["KODEX 200"]["price"] == 38900


def test_price_csv_upload(client):
    csv = "종목명,현재가\nKODEX 200,\"40,100\"\n".encode("cp949")
    r = client.post("/api/prices/upload", data={"dry_run": "false"}, files={"file": ("p.csv", io.BytesIO(csv), "text/csv")}).json()
    assert [x["name"] for x in r["updated"]] == ["KODEX 200"]
    assert {h["name"]: h["price"] for h in client.get("/api/entities/holdings").json()}["KODEX 200"] == 40100


def test_unknown_entity_kind(client):
    assert client.get("/api/entities/users").status_code == 404
    assert client.post("/api/entities/settings", json={}).status_code == 404
