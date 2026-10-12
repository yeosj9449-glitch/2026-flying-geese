"""SQLite 저장소 - 웹앱의 데이터베이스. 파일 하나(예: 우리집.db)에 가계 데이터와 로그인 계정을 담는다.

테이블은 model.py의 데이터셋과 1:1로 대응한다. 표준 라이브러리 sqlite3만 사용한다.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
from dataclasses import asdict
from datetime import date
from pathlib import Path

from household_finance import schema as s
from household_finance.model import (Account, Budget, Category, Dataset, Debt, Event, Goal, Holding, Insurance,
                                     Settings, Snapshot, Transaction)

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS categories (name TEXT PRIMARY KEY, grp TEXT NOT NULL, essential TEXT NOT NULL DEFAULT 'N', sort INTEGER);
CREATE TABLE IF NOT EXISTS rules (id INTEGER PRIMARY KEY, keyword TEXT NOT NULL, category TEXT NOT NULL, sort INTEGER);
CREATE TABLE IF NOT EXISTS accounts (id TEXT PRIMARY KEY, name TEXT, institution TEXT, type TEXT, owner TEXT, liquidity TEXT,
    memo TEXT, sort INTEGER);
CREATE TABLE IF NOT EXISTS snapshots (month TEXT, account_id TEXT, amount INTEGER NOT NULL, PRIMARY KEY (month, account_id));
CREATE TABLE IF NOT EXISTS transactions (id INTEGER PRIMARY KEY, day TEXT NOT NULL, desc TEXT, amount INTEGER NOT NULL,
    category TEXT, member TEXT, payment TEXT, source TEXT, memo TEXT);
CREATE INDEX IF NOT EXISTS tx_day ON transactions(day);
CREATE TABLE IF NOT EXISTS budgets (category TEXT PRIMARY KEY, basis TEXT, amount INTEGER, sort INTEGER);
CREATE TABLE IF NOT EXISTS holdings (id INTEGER PRIMARY KEY, account_id TEXT, name TEXT, code TEXT, asset_class TEXT,
    qty REAL, avg_price REAL, price REAL);
CREATE TABLE IF NOT EXISTS allocation (asset_class TEXT PRIMARY KEY, target REAL);
CREATE TABLE IF NOT EXISTS debts (id INTEGER PRIMARY KEY, name TEXT, account_id TEXT, rate REAL, maturity TEXT, method TEXT,
    payment INTEGER);
CREATE TABLE IF NOT EXISTS goals (id INTEGER PRIMARY KEY, name TEXT, owner TEXT, target INTEGER, start TEXT, end TEXT,
    accounts TEXT);
CREATE TABLE IF NOT EXISTS insurances (id INTEGER PRIMARY KEY, insured TEXT, insurer TEXT, product TEXT, coverages TEXT,
    premium INTEGER, maturity TEXT, renewable TEXT);
CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, day TEXT, desc TEXT, kind TEXT, amount INTEGER, member TEXT);
CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, member TEXT NOT NULL,
    salt TEXT NOT NULL, pw_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, created TEXT NOT NULL);
"""

DATA_TABLES = ["settings", "categories", "rules", "accounts", "snapshots", "transactions", "budgets", "holdings",
               "allocation", "debts", "goals", "insurances", "events"]


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def _date(v: str | None) -> date | None:
    return date.fromisoformat(v) if v else None


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def is_empty(self) -> bool:
        return self.conn.execute("SELECT COUNT(*) FROM settings").fetchone()[0] == 0

    # ------------------------------------------------------------ 데이터셋 전체 저장/불러오기
    def replace_dataset(self, ds: Dataset) -> None:
        """가계 데이터를 통째로 교체한다 (엑셀 가져오기·초기 설정용). 로그인 계정은 그대로 둔다."""
        with self.conn:
            for table in DATA_TABLES:
                self.conn.execute(f"DELETE FROM {table}")
            self.save_settings(ds.settings, commit=False)
            self.conn.executemany("INSERT INTO categories VALUES (?,?,?,?)",
                                  [(c.name, c.group, c.essential, i) for i, c in enumerate(ds.categories)])
            self.conn.executemany("INSERT INTO rules (keyword, category, sort) VALUES (?,?,?)",
                                  [(k, c, i) for i, (k, c) in enumerate(ds.rules)])
            self.conn.executemany("INSERT INTO accounts VALUES (?,?,?,?,?,?,?,?)",
                                  [(a.id, a.name, a.institution, a.type, a.owner, a.liquidity, a.memo, i)
                                   for i, a in enumerate(ds.accounts)])
            self.conn.executemany("INSERT OR REPLACE INTO snapshots VALUES (?,?,?)",
                                  [(x.month, x.account_id, int(x.amount)) for x in ds.snapshots])
            self.add_transactions(ds.transactions, commit=False)
            self.conn.executemany("INSERT INTO budgets VALUES (?,?,?,?)",
                                  [(b.category, b.basis, int(b.amount), i) for i, b in enumerate(ds.budgets)])
            self.conn.executemany("INSERT INTO holdings (account_id, name, code, asset_class, qty, avg_price, price) VALUES (?,?,?,?,?,?,?)",
                                  [(h.account_id, h.name, h.code, h.asset_class, h.qty, h.avg_price, h.price) for h in ds.holdings])
            self.conn.executemany("INSERT INTO allocation VALUES (?,?)", list(ds.allocation.items()))
            self.conn.executemany("INSERT INTO debts (name, account_id, rate, maturity, method, payment) VALUES (?,?,?,?,?,?)",
                                  [(d.name, d.account_id, d.rate, _iso(d.maturity), d.method, d.payment) for d in ds.debts])
            self.conn.executemany("INSERT INTO goals (name, owner, target, start, end, accounts) VALUES (?,?,?,?,?,?)",
                                  [(g.name, g.owner, g.target, _iso(g.start), _iso(g.end), json.dumps(g.accounts)) for g in ds.goals])
            self.conn.executemany("INSERT INTO insurances (insured, insurer, product, coverages, premium, maturity, renewable) VALUES (?,?,?,?,?,?,?)",
                                  [(p.insured, p.insurer, p.product, json.dumps(p.coverages, ensure_ascii=False), p.premium,
                                    _iso(p.maturity), p.renewable) for p in ds.insurances])
            self.conn.executemany("INSERT INTO events (day, desc, kind, amount, member) VALUES (?,?,?,?,?)",
                                  [(_iso(e.day), e.desc, e.kind, e.amount, e.member) for e in ds.events])

    def load_dataset(self) -> Dataset:
        q = lambda sql: self.conn.execute(sql).fetchall()
        ds = Dataset(settings=self.load_settings())
        ds.categories = [Category(r["name"], r["grp"], r["essential"]) for r in q("SELECT * FROM categories ORDER BY sort")]
        ds.rules = [(r["keyword"], r["category"]) for r in q("SELECT * FROM rules ORDER BY sort, id")]
        ds.accounts = [Account(r["id"], r["name"], r["institution"], r["type"], r["owner"], r["liquidity"], r["memo"] or "")
                       for r in q("SELECT * FROM accounts ORDER BY sort, id")]
        ds.snapshots = [Snapshot(r["month"], r["account_id"], r["amount"]) for r in q("SELECT * FROM snapshots ORDER BY month")]
        ds.transactions = self.transactions()
        ds.budgets = [Budget(r["category"], r["basis"], r["amount"]) for r in q("SELECT * FROM budgets ORDER BY sort")]
        ds.holdings = [Holding(r["account_id"], r["name"], r["code"], r["asset_class"], r["qty"], r["avg_price"], r["price"], r["id"])
                       for r in q("SELECT * FROM holdings ORDER BY id")]
        ds.allocation = {r["asset_class"]: r["target"] for r in q("SELECT * FROM allocation")}
        ds.debts = [Debt(r["name"], r["account_id"], r["rate"], _date(r["maturity"]), r["method"], r["payment"], r["id"])
                    for r in q("SELECT * FROM debts ORDER BY id")]
        ds.goals = [Goal(r["name"], r["owner"], r["target"], _date(r["start"]), _date(r["end"]), json.loads(r["accounts"]), r["id"])
                    for r in q("SELECT * FROM goals ORDER BY id")]
        ds.insurances = [Insurance(r["insured"], r["insurer"], r["product"], json.loads(r["coverages"]), r["premium"],
                                   _date(r["maturity"]), r["renewable"], r["id"]) for r in q("SELECT * FROM insurances ORDER BY id")]
        ds.events = [Event(_date(r["day"]), r["desc"], r["kind"], r["amount"], r["member"], r["id"])
                     for r in q("SELECT * FROM events ORDER BY id")]
        return ds

    # ------------------------------------------------------------ 설정
    def save_settings(self, st: Settings, commit: bool = True) -> None:
        rows = [(k, json.dumps(v, ensure_ascii=False)) for k, v in asdict(st).items()]
        self.conn.executemany("INSERT OR REPLACE INTO settings VALUES (?,?)", rows)
        if commit:
            self.conn.commit()

    def load_settings(self) -> Settings:
        values = {r["key"]: json.loads(r["value"]) for r in self.conn.execute("SELECT * FROM settings")}
        if "base_month" not in values:
            raise LookupError("데이터베이스가 비어 있습니다. 먼저 엑셀 파일을 가져오거나 새 가계를 만드세요.")
        known = Settings.__dataclass_fields__
        return Settings(**{k: v for k, v in values.items() if k in known})

    # ------------------------------------------------------------ 거래내역
    def transactions(self, month: str | None = None, category: str | None = None, member: str | None = None,
                     search: str | None = None) -> list[Transaction]:
        sql, args = "SELECT * FROM transactions WHERE 1=1", []
        if month:
            sql += " AND substr(day,1,7) = ?"
            args.append(month)
        if category:
            sql += " AND category = ?"
            args.append(category)
        if member:
            sql += " AND member = ?"
            args.append(member)
        if search:
            sql += " AND desc LIKE ?"
            args.append(f"%{search}%")
        sql += " ORDER BY day, id"
        return [Transaction(date.fromisoformat(r["day"]), r["desc"] or "", r["amount"], r["category"] or "", r["member"] or "",
                            r["payment"] or "", r["source"] or "", r["memo"] or "", r["id"])
                for r in self.conn.execute(sql, args)]

    def add_transactions(self, txs: list[Transaction], commit: bool = True) -> list[int]:
        ids = []
        for t in txs:
            cur = self.conn.execute(
                "INSERT INTO transactions (day, desc, amount, category, member, payment, source, memo) VALUES (?,?,?,?,?,?,?,?)",
                (t.day.isoformat(), t.desc, int(t.amount), t.category, t.member, t.payment, t.source, t.memo))
            ids.append(cur.lastrowid)
        if commit:
            self.conn.commit()
        return ids

    def update_transaction(self, tx_id: int, **fields) -> None:
        allowed = {"day", "desc", "amount", "category", "member", "payment", "memo"}
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"바꿀 수 없는 항목: {', '.join(sorted(bad))}")
        if not fields:
            return
        sets = ", ".join(f"{k} = ?" for k in fields)
        values = [v.isoformat() if isinstance(v, date) else v for v in fields.values()]
        cur = self.conn.execute(f"UPDATE transactions SET {sets} WHERE id = ?", (*values, tx_id))
        if cur.rowcount == 0:
            raise KeyError(f"거래 {tx_id}를 찾을 수 없습니다.")
        self.conn.commit()

    def delete_transaction(self, tx_id: int) -> None:
        if self.conn.execute("DELETE FROM transactions WHERE id = ?", (tx_id,)).rowcount == 0:
            raise KeyError(f"거래 {tx_id}를 찾을 수 없습니다.")
        self.conn.commit()

    # ------------------------------------------------------------ 스냅샷·예산·규칙
    def snapshot_months(self) -> list[str]:
        return [r[0] for r in self.conn.execute("SELECT DISTINCT month FROM snapshots ORDER BY month")]

    def set_snapshot(self, month: str, account_id: str, amount: int) -> None:
        self.conn.execute("INSERT OR REPLACE INTO snapshots VALUES (?,?,?)", (month, account_id, int(amount)))
        self.conn.commit()

    def set_budget(self, category: str, basis: str, amount: int) -> None:
        sort = self.conn.execute("SELECT COALESCE(MAX(sort), 0) + 1 FROM budgets").fetchone()[0]
        self.conn.execute("INSERT INTO budgets VALUES (?,?,?,?) ON CONFLICT(category) DO UPDATE SET basis=excluded.basis, "
                          "amount=excluded.amount", (category, basis, int(amount), sort))
        self.conn.commit()

    def add_rule(self, keyword: str, category: str, first: bool = True) -> None:
        """새 분류규칙. 기본은 맨 앞에 넣어 기존 규칙보다 먼저 적용되게 한다."""
        sort = (self.conn.execute("SELECT COALESCE(MIN(sort), 0) - 1 FROM rules").fetchone()[0] if first
                else self.conn.execute("SELECT COALESCE(MAX(sort), 0) + 1 FROM rules").fetchone()[0])
        self.conn.execute("INSERT INTO rules (keyword, category, sort) VALUES (?,?,?)", (keyword, category, sort))
        self.conn.commit()

    def set_holding_price(self, holding_id: int, price: float) -> None:
        if self.conn.execute("UPDATE holdings SET price = ? WHERE id = ?", (price, holding_id)).rowcount == 0:
            raise KeyError(f"보유종목 {holding_id}를 찾을 수 없습니다.")
        self.conn.commit()

    # ------------------------------------------------------------ 로그인 계정
    @staticmethod
    def _hash(password: str, salt: str) -> str:
        return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1).hex()

    def add_user(self, username: str, password: str, member: str) -> None:
        if member not in s.OWNERS[:2]:
            raise ValueError("로그인 계정의 구성원은 본인 또는 배우자여야 합니다.")
        if len(password) < 8:
            raise ValueError("비밀번호는 8자 이상이어야 합니다.")
        salt = secrets.token_hex(16)
        with self.conn:
            self.conn.execute("INSERT INTO users (username, member, salt, pw_hash) VALUES (?,?,?,?) "
                              "ON CONFLICT(username) DO UPDATE SET member=excluded.member, salt=excluded.salt, pw_hash=excluded.pw_hash",
                              (username, member, salt, self._hash(password, salt)))

    def users(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT id, username, member FROM users ORDER BY id")]

    def login(self, username: str, password: str) -> str | None:
        row = self.conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if row is None or not hmac.compare_digest(row["pw_hash"], self._hash(password, row["salt"])):
            return None
        token = secrets.token_urlsafe(32)
        with self.conn:
            self.conn.execute("INSERT INTO sessions VALUES (?,?,?)", (token, row["id"], date.today().isoformat()))
        return token

    def session_user(self, token: str | None) -> dict | None:
        if not token:
            return None
        row = self.conn.execute("SELECT u.id, u.username, u.member FROM sessions s JOIN users u ON u.id = s.user_id "
                                "WHERE s.token = ?", (token,)).fetchone()
        return dict(row) if row else None

    def logout(self, token: str) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
