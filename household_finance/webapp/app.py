"""웹앱 서버 (FastAPI). 실행: python -m household_finance serve --db 우리집.db

부부가 각자 계정으로 로그인해 같은 가계 데이터를 본다. 계산은 engine.py, 저장은 store.py가 맡고
이 파일은 그 둘을 HTTP API로 열어 주는 얇은 층이다. 화면은 static/의 단일 페이지 앱.
"""

from __future__ import annotations

import hmac
import shutil
import tempfile
import time
from collections import defaultdict
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Body, Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError
from starlette.background import BackgroundTask

from household_finance import prices, report
from household_finance import schema as s
from household_finance.engine import compute, shift_month
from household_finance.importer import plan_import, read_statement
from household_finance.model import Transaction, empty_dataset, load_workbook_dataset, sample_dataset
from household_finance.store import Store
from household_finance.workbook import build_workbook

STATIC = Path(__file__).parent / "static"
COOKIE = "hh_session"
MAX_UPLOAD = 10 * 1024 * 1024
MONTH_RE = r"^\d{4}-(0[1-9]|1[0-2])$"


# ---------------------------------------------------------------- 요청 본문
class UserIn(BaseModel):
    username: str = Field(min_length=2, max_length=40)
    password: str = Field(min_length=8, max_length=200)
    member: str


class SetupIn(BaseModel):
    code: str = ""                  # 설치 코드 (서버가 집 밖에 공개될 때만 필요)
    users: list[UserIn] = Field(min_length=1, max_length=2)
    start: str = "blank"            # blank | sample
    base_month: str | None = Field(default=None, pattern=MONTH_RE)


class LoginIn(BaseModel):
    username: str
    password: str


class TxIn(BaseModel):
    day: date
    desc: str = Field(max_length=200)
    amount: int = Field(gt=0)
    category: str
    member: str
    payment: str = ""
    memo: str = ""


class TxPatch(BaseModel):
    day: date | None = None
    desc: str | None = Field(default=None, max_length=200)
    amount: int | None = Field(default=None, gt=0)
    category: str | None = None
    member: str | None = None
    payment: str | None = None
    memo: str | None = None


class RuleIn(BaseModel):
    keyword: str = Field(min_length=1, max_length=60)
    category: str


class SnapshotIn(BaseModel):
    amounts: dict[str, int]


class CloseIn(BaseModel):
    month: str = Field(pattern=MONTH_RE)


class BudgetIn(BaseModel):
    basis: str = Field(pattern="^(월|연)$")
    amount: int = Field(ge=0)


class SettingsIn(BaseModel):
    t_saving: float | None = Field(default=None, ge=0, le=1)
    t_emergency: float | None = Field(default=None, ge=0, le=60)
    t_debt: float | None = Field(default=None, ge=0, le=5)
    t_dsr: float | None = Field(default=None, ge=0, le=5)
    band: float | None = Field(default=None, ge=0, le=1)
    invest_targets: dict[str, int] | None = None
    min_cash: int | None = Field(default=None, ge=0)
    alert_days: int | None = Field(default=None, ge=0, le=365)
    goal_tol: float | None = Field(default=None, ge=0, le=1)
    base_month: str | None = Field(default=None, pattern=MONTH_RE)


class PriceIn(BaseModel):
    price: float = Field(ge=0)


# 계좌·보유종목·부채·목표·보험·일정 - 화면의 추가/수정 양식이 보내는 전체 값
class AccountIn(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,12}$")
    name: str = Field(min_length=1, max_length=60)
    institution: str = Field(default="", max_length=60)
    type: str
    owner: str
    liquidity: str
    memo: str = Field(default="", max_length=200)


class HoldingIn(BaseModel):
    account_id: str
    name: str = Field(min_length=1, max_length=80)
    code: str = Field(default="", max_length=30)
    asset_class: str
    qty: float = Field(ge=0)
    avg_price: float = Field(ge=0)
    price: float = Field(ge=0)


class DebtIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    account_id: str
    rate: float = Field(ge=0, le=1)
    maturity: date | None = None
    method: str = Field(default="", max_length=30)
    payment: int = Field(ge=0)


class GoalIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    owner: str
    target: int | None = Field(default=None, ge=0)     # 비워 두면 비상자금처럼 자동 계산
    start: date
    end: date
    accounts: list[str] = Field(default_factory=list, max_length=3)


class InsuranceIn(BaseModel):
    insured: str
    insurer: str = Field(default="", max_length=60)
    product: str = Field(default="", max_length=80)
    coverages: dict[str, int] = Field(default_factory=dict)
    premium: int = Field(ge=0)
    maturity: date | None = None
    renewable: str = Field(default="N", pattern="^(Y|N)$")


class EventIn(BaseModel):
    day: date
    desc: str = Field(min_length=1, max_length=80)
    kind: str
    amount: int = Field(default=0, ge=0)
    member: str


ENTITY_MODELS = {"accounts": AccountIn, "holdings": HoldingIn, "debts": DebtIn, "goals": GoalIn,
                 "insurances": InsuranceIn, "events": EventIn}


class AllocationIn(BaseModel):
    targets: dict[str, float]


class RefreshIn(BaseModel):
    dry_run: bool = False


# ---------------------------------------------------------------- 앱
LOGIN_MAX_FAILS = 5
LOGIN_WINDOW = 15 * 60        # 초


def create_app(db_path: str | Path, today: date | None = None, price_fetcher=None, setup_code: str | None = None,
               secure_cookies: bool = False, mail: "report.MailConfig | None | bool" = True, mail_sender=None) -> FastAPI:
    """setup_code: 처음 설정에 필요한 설치 코드 (집 밖에 공개된 서버에서 남이 먼저 가계를 만들지 못하게).
    secure_cookies: HTTPS 뒤에서 실행할 때 True - 로그인 쿠키를 암호화 연결로만 보낸다.
    mail: 리포트 메일 설정. True(기본)면 환경변수(HH_SMTP_*)에서 읽는다.
    today·price_fetcher·mail_sender는 테스트에서 날짜·시세 조회·메일 발송을 고정할 때만 쓴다."""
    mail = report.MailConfig.from_env() if mail is True else (mail or None)
    store = Store(db_path)
    app = FastAPI(title="우리집 주식회사", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    failures: dict[str, list[float]] = defaultdict(list)   # 아이디·IP별 최근 로그인 실패 시각

    @app.middleware("http")
    async def protect(request: Request, call_next):
        # 다른 사이트에서 몰래 보내는 저장 요청 차단 (SameSite 쿠키에 더해 한 겹 더)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin and urlparse(origin).netloc != request.headers.get("host"):
                return JSONResponse({"detail": "다른 사이트에서 온 요청은 받지 않습니다."}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                                                       "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if secure_cookies:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    def throttled(*keys: str) -> bool:
        cutoff = time.monotonic() - LOGIN_WINDOW
        for k in keys:
            failures[k] = [x for x in failures[k] if x > cutoff]
        return any(len(failures[k]) >= LOGIN_MAX_FAILS for k in keys)

    def now() -> date:
        return today or date.today()

    def user(request: Request) -> dict:
        u = store.session_user(request.cookies.get(COOKIE))
        if u is None:
            raise HTTPException(401, "로그인이 필요합니다.")
        return u

    def data():
        try:
            return store.load_dataset()
        except LookupError as exc:
            raise HTTPException(409, str(exc)) from exc

    def set_cookie(response: Response, token: str) -> None:
        response.set_cookie(COOKIE, token, httponly=True, samesite="strict", secure=secure_cookies,
                            max_age=60 * 60 * 24 * Store.SESSION_DAYS)

    def check_category(name: str) -> None:
        if name and name != s.UNCATEGORIZED and name not in {c.name for c in store.load_dataset().categories}:
            raise HTTPException(422, f"없는 카테고리입니다: {name}")

    def check_member(name: str) -> None:
        if name not in s.OWNERS:
            raise HTTPException(422, f"구성원은 {', '.join(s.OWNERS)} 중 하나여야 합니다.")

    async def read_upload(file: UploadFile, suffixes: tuple[str, ...]) -> Path:
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in suffixes:
            raise HTTPException(422, f"{', '.join(suffixes)} 파일만 올릴 수 있습니다.")
        content = await file.read(MAX_UPLOAD + 1)
        if len(content) > MAX_UPLOAD:
            raise HTTPException(413, "파일이 너무 큽니다 (최대 10MB).")
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        tmp.write(content)
        tmp.close()
        return Path(tmp.name)

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    # ------------------------------------------------------------ 계정
    @app.get("/api/status")
    def status():
        return {"setup_needed": not store.users(), "has_data": not store.is_empty(), "setup_code_required": bool(setup_code)}

    @app.post("/api/setup")
    def setup(body: SetupIn, response: Response):
        if store.users():
            raise HTTPException(409, "이미 설정이 끝났습니다. 로그인하세요.")
        if setup_code and not hmac.compare_digest(body.code.strip().upper(), setup_code.upper()):
            raise HTTPException(403, "설치 코드가 맞지 않습니다. 서버를 켠 화면에 표시된 코드를 넣으세요.")
        members = [u.member for u in body.users]
        if len(set(members)) != len(members) or not set(members) <= {"본인", "배우자"}:
            raise HTTPException(422, "계정은 본인·배우자 각각 하나씩 만들 수 있습니다.")
        for u in body.users:
            store.add_user(u.username, u.password, u.member)
        if store.is_empty():
            if body.start == "sample":
                store.replace_dataset(sample_dataset())
            else:
                base = body.base_month or shift_month(f"{now().year}-{now().month:02d}", -1)
                store.replace_dataset(empty_dataset(base))
        set_cookie(response, store.login(body.users[0].username, body.users[0].password))
        return {"ok": True}

    @app.post("/api/login")
    def login(body: LoginIn, request: Request, response: Response):
        keys = (f"user:{body.username}", f"ip:{request.client.host if request.client else '?'}")
        if throttled(*keys):
            raise HTTPException(429, "로그인 실패가 너무 많습니다. 15분 뒤에 다시 시도하세요.")
        token = store.login(body.username, body.password)
        if token is None:
            for k in keys:
                failures[k].append(time.monotonic())
            raise HTTPException(401, "아이디 또는 비밀번호가 맞지 않습니다.")
        for k in keys:
            failures.pop(k, None)
        set_cookie(response, token)
        return {"ok": True}

    @app.post("/api/logout")
    def logout(request: Request, response: Response):
        if request.cookies.get(COOKIE):
            store.logout(request.cookies[COOKIE])
        response.delete_cookie(COOKIE)
        return {"ok": True}

    @app.get("/api/me")
    def me(u: dict = Depends(user)):
        return {**u, "users": store.users()}

    @app.post("/api/users")
    def add_user(body: UserIn, u: dict = Depends(user)):
        try:
            store.add_user(body.username, body.password, body.member)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"users": store.users()}

    # ------------------------------------------------------------ 조회
    @app.get("/api/meta")
    def meta(u: dict = Depends(user)):
        ds = data()
        months = sorted(set(store.snapshot_months()) | {t.month for t in ds.transactions} | {ds.settings.base_month})
        return {"base_month": ds.settings.base_month, "months": months, "owners": s.OWNERS, "views": s.VIEW_OPTIONS,
                "members": s.MEMBERS, "account_types": s.ACCOUNT_TYPES, "liquidity": s.LIQUIDITY,
                "asset_classes": s.ASSET_CLASSES, "coverages": s.COVERAGES, "event_kinds": s.EVENT_KINDS,
                "allocation": ds.allocation, "mail_enabled": mail is not None, "mail_to": mail.to if mail else [],
                "groups": s.GROUPS, "categories": [c.__dict__ for c in ds.categories],
                "accounts": [a.__dict__ for a in ds.accounts], "settings": ds.settings.__dict__}

    @app.get("/api/dashboard")
    def dashboard(view: str = "전체", month: str | None = None, u: dict = Depends(user)):
        if view not in s.VIEW_OPTIONS:
            raise HTTPException(422, "보기 값이 올바르지 않습니다.")
        return compute(data(), view, month, now())

    @app.get("/api/transactions")
    def transactions(month: str | None = None, category: str | None = None, member: str | None = None,
                     q: str | None = None, u: dict = Depends(user)):
        groups = {c.name: c.group for c in data().categories}
        rows = store.transactions(month=month, category=category, member=member, search=q)
        return [{**t.__dict__, "day": t.day.isoformat(), "group": groups.get(t.category, s.UNCATEGORIZED)} for t in rows]

    # ------------------------------------------------------------ 거래 편집
    @app.post("/api/transactions")
    def add_tx(body: TxIn, u: dict = Depends(user)):
        check_category(body.category)
        check_member(body.member)
        (tx_id,) = store.add_transactions([Transaction(body.day, body.desc, body.amount, body.category, body.member,
                                                       body.payment, f"직접 입력({u['username']})", body.memo)])
        return {"id": tx_id}

    @app.patch("/api/transactions/{tx_id}")
    def edit_tx(tx_id: int, body: TxPatch, u: dict = Depends(user)):
        fields = body.model_dump(exclude_none=True)
        if "category" in fields:
            check_category(fields["category"])
        if "member" in fields:
            check_member(fields["member"])
        try:
            store.update_transaction(tx_id, **fields)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"ok": True}

    @app.delete("/api/transactions/{tx_id}")
    def delete_tx(tx_id: int, u: dict = Depends(user)):
        try:
            store.delete_transaction(tx_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"ok": True}

    @app.post("/api/rules")
    def add_rule(body: RuleIn, u: dict = Depends(user)):
        """분류규칙 추가 + 같은 키워드의 미분류 거래를 바로 다시 분류."""
        check_category(body.category)
        store.add_rule(body.keyword.strip(), body.category)
        fixed = 0
        for t in store.transactions(category=s.UNCATEGORIZED):
            if body.keyword.strip().lower() in t.desc.lower():
                store.update_transaction(t.id, category=body.category)
                fixed += 1
        return {"reclassified": fixed}

    # ------------------------------------------------------------ 가져오기·내보내기
    @app.post("/api/import/statement")
    async def import_statement(file: UploadFile = File(...), member: str = Form(...), payment: str = Form(""),
                               dry_run: bool = Form(False), u: dict = Depends(user)):
        check_member(member)
        path = await read_upload(file, (".csv", ".xlsx"))
        try:
            rows, skipped = read_statement(path)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        finally:
            path.unlink(missing_ok=True)
        ds = data()
        existing = [(t.day, t.desc, t.amount, t.member) for t in ds.transactions]
        result = plan_import(rows, existing, ds.rules, member, payment, file.filename or "업로드")
        if not dry_run and result.added:
            store.add_transactions([Transaction(t.day, t.desc, t.amount, t.category, t.member, t.payment, t.source, t.memo)
                                    for t in result.added])
        return {"dry_run": dry_run, "added": [{**t.__dict__, "day": t.day.isoformat()} for t in result.added],
                "duplicates": result.duplicates, "skipped": skipped, "uncategorized": len(result.uncategorized)}

    @app.post("/api/import/workbook")
    async def import_workbook(file: UploadFile = File(...), u: dict = Depends(user)):
        """1단계 엑셀 파일로 가계 데이터를 통째로 교체 (로그인 계정은 유지)."""
        path = await read_upload(file, (".xlsx",))
        try:
            ds = load_workbook_dataset(path)
        except Exception as exc:   # 형식이 다른 엑셀은 어디서든 깨질 수 있다
            raise HTTPException(422, f"우리집 자산관리 엑셀 형식이 아닙니다: {exc}") from exc
        finally:
            path.unlink(missing_ok=True)
        store.replace_dataset(ds)
        return {"transactions": len(ds.transactions), "accounts": len(ds.accounts), "base_month": ds.settings.base_month}

    @app.get("/api/export.xlsx")
    def export(u: dict = Depends(user)):
        ds = data()
        folder = Path(tempfile.mkdtemp())
        out = folder / f"우리집_자산관리_{ds.settings.base_month}.xlsx"
        build_workbook(out, dataset=ds)
        return FileResponse(out, filename=out.name, background=BackgroundTask(shutil.rmtree, folder, ignore_errors=True),
                            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    # ------------------------------------------------------------ 월말 결산
    @app.get("/api/snapshots/{month}")
    def snapshots(month: str, u: dict = Depends(user)):
        ds = data()
        prev = shift_month(month, -1)
        cur = {(x.month, x.account_id): x.amount for x in ds.snapshots}
        return {"month": month, "previous_month": prev, "rows": [
            {**a.__dict__, "amount": cur.get((month, a.id)), "previous": cur.get((prev, a.id))} for a in ds.accounts]}

    @app.put("/api/snapshots/{month}")
    def save_snapshots(month: str, body: SnapshotIn, u: dict = Depends(user)):
        known = {a.id for a in data().accounts}
        unknown = set(body.amounts) - known
        if unknown:
            raise HTTPException(422, f"없는 계좌: {', '.join(sorted(unknown))}")
        for acc, amount in body.amounts.items():
            store.set_snapshot(month, acc, amount)
        return {"saved": len(body.amounts)}

    @app.post("/api/close-month")
    def close_month(body: CloseIn, u: dict = Depends(user)):
        """새 달 결산 시작: 잔액이 없는 계좌는 직전 달 잔액을 복사하고 기준월을 그 달로 바꾼다."""
        ds = data()
        cur = {(x.month, x.account_id): x.amount for x in ds.snapshots}
        prev = shift_month(body.month, -1)
        copied = 0
        for a in ds.accounts:
            if (body.month, a.id) not in cur:
                store.set_snapshot(body.month, a.id, cur.get((prev, a.id), 0))
                copied += 1
        ds.settings.base_month = body.month
        store.save_settings(ds.settings)
        return {"month": body.month, "copied": copied}

    # ------------------------------------------------------------ 예산·설정·시세
    @app.put("/api/budgets/{category}")
    def save_budget(category: str, body: BudgetIn, u: dict = Depends(user)):
        check_category(category)
        store.set_budget(category, body.basis, body.amount)
        return {"ok": True}

    @app.put("/api/settings")
    def save_settings(body: SettingsIn, u: dict = Depends(user)):
        st = data().settings
        for k, v in body.model_dump(exclude_none=True).items():
            if k == "invest_targets":
                if set(v) - set(s.OWNERS):
                    raise HTTPException(422, "투자 목표는 본인·배우자·공동만 정할 수 있습니다.")
                v = {**st.invest_targets, **v}
            setattr(st, k, v)
        store.save_settings(st)
        return st.__dict__

    @app.patch("/api/holdings/{holding_id}")
    def set_price(holding_id: int, body: PriceIn, u: dict = Depends(user)):
        try:
            store.set_holding_price(holding_id, body.price)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"ok": True}

    # ------------------------------------------------------------ 계좌·보유종목·부채·목표·보험·일정
    def validate_entity(kind: str, item, editing_key=None) -> dict:
        accounts = {a.id: a for a in store.load_dataset().accounts}
        def need(ok: bool, msg: str) -> None:
            if not ok:
                raise HTTPException(422, msg)

        if kind == "accounts":
            need(item.type in s.ACCOUNT_TYPES, f"유형은 {', '.join(s.ACCOUNT_TYPES)} 중 하나입니다.")
            need(item.owner in s.OWNERS, f"소유자는 {', '.join(s.OWNERS)} 중 하나입니다.")
            need(item.liquidity in s.LIQUIDITY, f"유동성은 {', '.join(s.LIQUIDITY)} 중 하나입니다.")
            need(editing_key is None or item.id == editing_key, "계좌ID는 바꿀 수 없습니다.")
        if kind in ("holdings", "debts"):
            need(item.account_id in accounts, f"없는 계좌입니다: {item.account_id}")
        if kind == "holdings":
            need(item.asset_class in s.ASSET_CLASSES, f"자산군은 {', '.join(s.ASSET_CLASSES)} 중 하나입니다.")
        if kind == "debts":
            need(accounts[item.account_id].type == s.LIABILITY, "부채는 유형이 '부채'인 계좌에 연결해야 합니다.")
        if kind == "goals":
            need(item.owner in s.MEMBERS, f"담당은 {', '.join(s.MEMBERS)} 중 하나입니다.")
            need(item.end > item.start, "목표일은 시작일보다 뒤여야 합니다.")
            missing = [a for a in item.accounts if a not in accounts]
            need(not missing, f"없는 계좌입니다: {', '.join(missing)}")
        if kind == "insurances":
            need(item.insured in s.MEMBERS, f"피보험자는 {', '.join(s.MEMBERS)} 중 하나입니다.")
            bad = set(item.coverages) - set(s.COVERAGES)
            need(not bad, f"보장항목은 {', '.join(s.COVERAGES)} 중에서 고릅니다.")
        if kind == "events":
            need(item.kind in s.EVENT_KINDS, f"구분은 {', '.join(s.EVENT_KINDS)} 중 하나입니다.")
            need(item.member in s.OWNERS, f"구성원은 {', '.join(s.OWNERS)} 중 하나입니다.")
        return item.model_dump()

    def parse_entity(kind: str, body: dict):
        if kind not in ENTITY_MODELS:
            raise HTTPException(404, f"편집할 수 없는 항목입니다: {kind}")
        try:
            return ENTITY_MODELS[kind].model_validate(body)
        except ValidationError as exc:
            raise HTTPException(422, "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())) from exc

    def entity_key(kind: str, key: str):
        return key if kind == "accounts" else int(key) if key.isdigit() else -1

    @app.get("/api/entities/{kind}")
    def list_entities(kind: str, u: dict = Depends(user)):
        if kind not in ENTITY_MODELS:
            raise HTTPException(404, f"편집할 수 없는 항목입니다: {kind}")
        return store.list_entities(kind)

    @app.post("/api/entities/{kind}")
    def create_entity(kind: str, body: dict = Body(...), u: dict = Depends(user)):
        data_ = validate_entity(kind, parse_entity(kind, body))
        try:
            return {"id": store.create_entity(kind, data_)}
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.put("/api/entities/{kind}/{key}")
    def update_entity(kind: str, key: str, body: dict = Body(...), u: dict = Depends(user)):
        data_ = validate_entity(kind, parse_entity(kind, body), editing_key=key if kind == "accounts" else None)
        try:
            store.update_entity(kind, entity_key(kind, key), data_)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"ok": True}

    @app.delete("/api/entities/{kind}/{key}")
    def delete_entity(kind: str, key: str, u: dict = Depends(user)):
        if kind not in ENTITY_MODELS:
            raise HTTPException(404, f"편집할 수 없는 항목입니다: {kind}")
        try:
            store.delete_entity(kind, entity_key(kind, key))
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"ok": True}

    @app.put("/api/allocation")
    def save_allocation(body: AllocationIn, u: dict = Depends(user)):
        if set(body.targets) != set(s.ASSET_CLASSES):
            raise HTTPException(422, f"자산군 {', '.join(s.ASSET_CLASSES)}의 목표 비중을 모두 보내야 합니다.")
        if any(v < 0 for v in body.targets.values()) or abs(sum(body.targets.values()) - 1) > 0.001:
            raise HTTPException(422, "목표 비중의 합은 100%여야 합니다.")
        store.set_allocation(body.targets)
        return {"ok": True}

    # ------------------------------------------------------------ 시세 갱신
    def apply_prices(report: dict, dry_run: bool) -> dict:
        if not dry_run:
            for item in report["updated"]:
                store.set_holding_price(item["id"], item["new"])
        return {**report, "dry_run": dry_run}

    @app.post("/api/prices/refresh")
    def refresh_prices(body: RefreshIn, u: dict = Depends(user)):
        fetch = price_fetcher or prices.fetch_naver
        return apply_prices(prices.refresh(store.list_entities("holdings"), fetch), body.dry_run)

    @app.post("/api/prices/upload")
    async def upload_prices(file: UploadFile = File(...), dry_run: bool = Form(False), u: dict = Depends(user)):
        path = await read_upload(file, (".csv",))
        try:
            raw = path.read_bytes()
            text = next((raw.decode(enc) for enc in ("utf-8-sig", "cp949") if _decodes(raw, enc)), None)
            if text is None:
                raise HTTPException(422, "파일 인코딩을 알 수 없습니다.")
            table = prices.parse_price_csv(text)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        finally:
            path.unlink(missing_ok=True)
        return apply_prices(prices.match_prices(store.list_entities("holdings"), table), dry_run)

    # ------------------------------------------------------------ 결산 리포트 메일
    @app.get("/api/report.html")
    def report_preview(month: str | None = None, u: dict = Depends(user)):
        subject, html, _text = report.build(compute(data(), "전체", month, now()))
        return Response(f"<!doctype html><meta charset='utf-8'><title>{subject}</title>{html}", media_type="text/html")

    @app.post("/api/report/send")
    def report_send(body: CloseIn | None = None, u: dict = Depends(user)):
        if mail is None:
            raise HTTPException(400, "메일 설정이 없습니다. 서버를 켤 때 HH_SMTP_HOST·HH_SMTP_USER·HH_SMTP_PASSWORD·HH_MAIL_TO를 지정하세요.")
        subject, html, text = report.build(compute(data(), "전체", body.month if body else None, now()))
        try:
            (mail_sender or report.send)(mail, subject, html, text)
        except Exception as exc:   # 인증 실패·연결 실패를 그대로 알려 준다
            raise HTTPException(502, f"메일을 보내지 못했습니다: {exc}") from exc
        return {"sent_to": mail.to, "subject": subject}

    return app


def _decodes(raw: bytes, encoding: str) -> bool:
    try:
        raw.decode(encoding)
        return True
    except UnicodeDecodeError:
        return False
