"""웹앱 서버 (FastAPI). 실행: python -m household_finance serve --db 우리집.db

부부가 각자 계정으로 로그인해 같은 가계 데이터를 본다. 계산은 engine.py, 저장은 store.py가 맡고
이 파일은 그 둘을 HTTP API로 열어 주는 얇은 층이다. 화면은 static/의 단일 페이지 앱.
"""

from __future__ import annotations

import shutil
import tempfile
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

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


# ---------------------------------------------------------------- 앱
def create_app(db_path: str | Path, today: date | None = None) -> FastAPI:
    """today는 테스트에서 날짜를 고정할 때만 쓴다 (기본: 실행 시점의 오늘)."""
    store = Store(db_path)
    app = FastAPI(title="우리집 주식회사", docs_url=None, redoc_url=None)
    app.state.store = store
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

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
        response.set_cookie(COOKIE, token, httponly=True, samesite="strict", max_age=60 * 60 * 24 * 30)

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
        return {"setup_needed": not store.users(), "has_data": not store.is_empty()}

    @app.post("/api/setup")
    def setup(body: SetupIn, response: Response):
        if store.users():
            raise HTTPException(409, "이미 설정이 끝났습니다. 로그인하세요.")
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
    def login(body: LoginIn, response: Response):
        token = store.login(body.username, body.password)
        if token is None:
            raise HTTPException(401, "아이디 또는 비밀번호가 맞지 않습니다.")
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

    return app
