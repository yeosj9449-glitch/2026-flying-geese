import sqlite3
from datetime import date

import pytest
from fastapi.testclient import TestClient

from household_finance import report
from household_finance.engine import compute
from household_finance.model import sample_dataset
from household_finance.scheduler import run_once
from household_finance.store import Store
from household_finance.webapp.app import create_app

TODAY = date(2026, 10, 12)
USER = {"username": "jiwoo", "password": "password-1", "member": "본인"}
MAIL = report.MailConfig("smtp.example.com", 587, "me@example.com", "app-pass", "me@example.com", ["me@example.com", "spouse@example.com"])


class FakeSMTP:
    sent: list = []

    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append(("login", user))

    def send_message(self, msg):
        self.calls.append("send")
        FakeSMTP.sent.append(msg)


# ---------------------------------------------------------------- 리포트
def test_report_contains_every_section_and_escapes_text():
    ds = sample_dataset()
    ds.events[1].desc = "<script>x</script> 자동차보험"
    subject, html, text = report.build(compute(ds, today=TODAY))
    assert subject == "[우리집 주식회사] 2026년 9월 월간 결산 · 알림 8건"
    for section in ["1. 핵심 지표", "2. 손익", "3. 재무상태", "4. 예산 통제", "5. 목표 진척", "6. 다음 달 할 일"]:
        assert section in html
    assert "734,593,000원" in html and "외식" in html
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "순자산" in text and "다음 달 할 일" in text


def test_mail_config_from_env():
    assert report.MailConfig.from_env({}) is None
    cfg = report.MailConfig.from_env({"HH_SMTP_HOST": "smtp.gmail.com", "HH_SMTP_USER": "a@gmail.com", "HH_SMTP_PASSWORD": "x",
                                      "HH_MAIL_TO": "a@gmail.com, b@gmail.com "})
    assert (cfg.port, cfg.sender, cfg.to) == (587, "a@gmail.com", ["a@gmail.com", "b@gmail.com"])


def test_send_uses_starttls_login_and_html_alternative():
    smtp = FakeSMTP()
    FakeSMTP.sent = []
    report.send(MAIL, "제목", "<p>본문</p>", "본문", smtp_factory=lambda: smtp)
    assert smtp.calls == ["starttls", ("login", "me@example.com"), "send"]
    msg = FakeSMTP.sent[0]
    assert msg["To"] == "me@example.com, spouse@example.com" and msg["Subject"] == "제목"
    assert [p.get_content_type() for p in msg.iter_parts()] == ["text/plain", "text/html"]


# ---------------------------------------------------------------- 예약 작업·백업
@pytest.fixture
def store(tmp_path):
    st = Store(tmp_path / "home.db")
    st.replace_dataset(sample_dataset())
    return st


def test_scheduler_backs_up_daily_and_reports_monthly(store, tmp_path):
    sent = []
    sender = lambda cfg, subject, html, text: sent.append(subject)
    first = run_once(store, date(2026, 10, 1), MAIL, 1, tmp_path / "bk", sender=sender)
    assert len(first) == 2 and len(sent) == 1
    assert run_once(store, date(2026, 10, 1), MAIL, 1, tmp_path / "bk", sender=sender) == []      # 같은 날 다시: 할 일 없음
    assert [x.startswith("백업") for x in run_once(store, date(2026, 10, 2), MAIL, 1, tmp_path / "bk", sender=sender)] == [True]
    assert len(sent) == 1                                                                       # 이번 달 리포트는 한 번만
    run_once(store, date(2026, 11, 1), MAIL, 1, None, sender=sender)
    assert len(sent) == 2


def test_scheduler_waits_for_report_day_and_retries_after_failure(store):
    assert run_once(store, date(2026, 10, 2), MAIL, 5, None, sender=lambda *a: None) == []
    def broken(*a):
        raise OSError("connection refused")
    assert run_once(store, date(2026, 10, 5), MAIL, 5, None, sender=broken)[0].startswith("리포트 발송 실패")
    ok = run_once(store, date(2026, 10, 5), MAIL, 5, None, sender=lambda *a: None)              # 다음 시간에 재시도
    assert ok and ok[0].startswith("리포트 발송:")


def test_backup_is_a_working_copy_and_prunes_old_files(store, tmp_path):
    folder = tmp_path / "bk"
    folder.mkdir()
    for d in ["2026-09-01", "2026-09-02", "2026-09-03"]:
        (folder / f"home_{d}.db").write_bytes(b"old")
    path = store.backup(folder, keep=2)
    assert sorted(p.name for p in folder.iterdir()) == ["home_2026-09-03.db", path.name]
    assert sqlite3.connect(path).execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == len(sample_dataset().transactions)


# ---------------------------------------------------------------- 보안
def make_client(tmp_path, **kw):
    return TestClient(create_app(tmp_path / "web.db", today=TODAY, **kw))


def test_setup_code_required_when_configured(tmp_path):
    c = make_client(tmp_path, setup_code="7F3K9Q")
    assert c.get("/api/status").json()["setup_code_required"] is True
    assert c.post("/api/setup", json={"users": [USER], "code": "WRONG1"}).status_code == 403
    assert c.post("/api/setup", json={"users": [USER], "code": "7f3k9q"}).status_code == 200      # 대소문자 무시


def test_login_is_throttled_after_repeated_failures(tmp_path):
    c = make_client(tmp_path)
    c.post("/api/setup", json={"users": [USER], "start": "blank"})
    anon = TestClient(c.app)
    for _ in range(5):
        assert anon.post("/api/login", json={"username": "jiwoo", "password": "guess-1234"}).status_code == 401
    blocked = anon.post("/api/login", json={"username": "jiwoo", "password": "password-1"})
    assert blocked.status_code == 429                                                          # 맞는 비밀번호도 잠시 막힘


def test_sessions_are_hashed_and_expire(tmp_path):
    c = make_client(tmp_path)
    c.post("/api/setup", json={"users": [USER], "start": "blank"})
    token = c.cookies.get("hh_session")
    db = sqlite3.connect(tmp_path / "web.db")
    stored = db.execute("SELECT token FROM sessions").fetchone()[0]
    assert stored != token and len(stored) == 64                                               # 원래 토큰은 DB에 없음
    assert c.get("/api/me").status_code == 200
    db.execute("UPDATE sessions SET created = '2020-01-01'")
    db.commit()
    assert c.get("/api/me").status_code == 401


def test_cross_site_writes_are_rejected_and_headers_set(tmp_path):
    c = make_client(tmp_path)
    c.post("/api/setup", json={"users": [USER], "start": "sample"})
    r = c.post("/api/rules", json={"keyword": "x", "category": "식비"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert c.post("/api/rules", json={"keyword": "x", "category": "식비"}, headers={"Origin": "http://testserver"}).status_code == 200
    page = c.get("/")
    assert page.headers["X-Frame-Options"] == "DENY" and "default-src 'self'" in page.headers["Content-Security-Policy"]


def test_secure_cookie_behind_https(tmp_path):
    c = make_client(tmp_path, secure_cookies=True)
    r = c.post("/api/setup", json={"users": [USER], "start": "blank"})
    assert "secure" in r.headers["set-cookie"].lower() and "Strict-Transport-Security" in r.headers


def test_report_endpoints(tmp_path):
    sent = []
    c = make_client(tmp_path, mail=MAIL, mail_sender=lambda cfg, s, h, t: sent.append((cfg.to, s)))
    c.post("/api/setup", json={"users": [USER], "start": "sample"})
    assert c.get("/api/meta").json()["mail_enabled"] is True
    preview = c.get("/api/report.html")
    assert preview.status_code == 200 and "월간 결산" in preview.text
    assert c.post("/api/report/send", json={"month": "2026-09"}).json()["sent_to"] == MAIL.to
    assert sent and sent[0][1].startswith("[우리집 주식회사] 2026년 9월")
    no_mail = TestClient(create_app(tmp_path / "other.db", today=TODAY, mail=None))
    no_mail.post("/api/setup", json={"users": [USER], "start": "sample"})
    assert no_mail.post("/api/report/send").status_code == 400


def test_scheduler_running_before_setup_does_not_block_first_setup(tmp_path):
    """배포 시 예약 작업이 처음 설정보다 먼저 돌아 백업 기록만 남긴 경우 (실제 Docker 배포 시험에서 발견)."""
    st = Store(tmp_path / "web.db")
    run_once(st, TODAY, None, 1, tmp_path / "bk")
    assert st.is_empty()
    c = make_client(tmp_path)
    assert c.get("/api/status").json()["has_data"] is False
    assert c.post("/api/setup", json={"users": [USER], "start": "sample"}).status_code == 200
    assert c.get("/api/dashboard").status_code == 200
