"""계산 엔진 - 스프레드시트의 보고 수식(손익·재무상태표·예산·투자·부채·목표·보험·현금흐름·대시보드)을
파이썬으로 옮긴 것. 웹앱은 이 결과를 그대로 화면에 그린다.

스프레드시트와 숫자가 1원·0.1%p까지 같아야 한다 - tests/test_household_engine.py가
LibreOffice로 재계산한 샘플 워크북 값과 비교한다. 수식을 바꿀 때는 workbook.py와 함께 고친다.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from household_finance import schema as s
from household_finance.model import Dataset

# ---------------------------------------------------------------- 엑셀식 반올림·서식
def xround(x: float, digits: int = 0) -> float:
    """엑셀 ROUND: 0.5는 0에서 먼 쪽으로 (파이썬 round는 짝수 쪽)."""
    m = 10 ** digits
    return math.copysign(math.floor(abs(x) * m + 0.5 + 1e-9) / m, x)


def won(x: float) -> str:
    """TEXT(x, "#,##0")"""
    v = int(xround(x))
    return f"{v:,}" if v >= 0 else f"-{abs(v):,}"


def signed_won(x: float) -> str:
    """TEXT(x, "+#,##0;-#,##0")"""
    v = int(xround(x))
    return f"+{v:,}" if v >= 0 else f"-{abs(v):,}"


def pct0(x: float) -> str:
    return f"{int(xround(x * 100))}%"


def pct1(x: float) -> str:
    return f"{xround(x * 100, 1):.1f}%"


def signed_pct0(x: float) -> str:
    """TEXT(x, "+0%;-0%")"""
    v = int(xround(x * 100))
    return f"+{v}%" if x >= 0 else f"-{abs(v)}%"


def shift_month(month: str, k: int) -> str:
    y, m = int(month[:4]), int(month[5:7])
    total = y * 12 + (m - 1) + k
    return f"{total // 12}-{total % 12 + 1:02d}"


def month_no(month: str) -> int:
    return int(month[:4]) * 100 + int(month[5:7])


def ratio(a: float, b: float) -> float:
    return 0.0 if b == 0 else a / b


# ---------------------------------------------------------------- 결과 묶음
@dataclass
class Card:
    kpi: str
    label: str
    value: float | None
    format: str     # won | pct | months
    note: str
    status: str


class Engine:
    """한 번의 계산 (기준월 × 보기 × 오늘 날짜)."""

    def __init__(self, ds: Dataset, view: str = "전체", base_month: str | None = None, today: date | None = None):
        if view not in s.VIEW_OPTIONS:
            raise ValueError(f"보기는 {', '.join(s.VIEW_OPTIONS)} 중 하나여야 합니다: {view}")
        self.ds = ds
        self.view = view
        self.base = base_month or ds.settings.base_month
        self.prev = shift_month(self.base, -1)
        self.today = today or date.today()
        self.months = [shift_month(self.base, k) for k in range(-11, 1)]
        self.cat = {c.name: c for c in ds.categories}
        self.acc = {a.id: a for a in ds.accounts}
        self._index()

    def match(self, member: str) -> bool:
        """SUMIFS 조회조건: 전체 = 비어 있지 않은 모든 구성원."""
        return bool(member) if self.view == "전체" else member == self.view

    # ------------------------------------------------------------ 인덱스
    def _index(self) -> None:
        self.tx_cat = defaultdict(float)     # (월, 카테고리) → 금액 (보기 기준)
        self.tx_group = defaultdict(float)   # (월, 대분류)
        self.tx_ess = defaultdict(float)     # 월 → 필수지출
        for t in self.ds.transactions:
            if not self.match(t.member) or not t.category:
                continue
            c = self.cat.get(t.category)
            group = c.group if c else s.UNCATEGORIZED
            self.tx_cat[(t.month, t.category)] += t.amount
            self.tx_group[(t.month, group)] += t.amount
            if (c.essential if c else "N") == "Y":
                self.tx_ess[t.month] += t.amount

    def snap_sum(self, month: str, *, type_: str | None = None, not_type: str | None = None, liquidity: str | None = None,
                 owner: str | None = None, account: str | None = None, use_view: bool = True) -> float:
        total = 0.0
        for sn in self.ds.snapshots:
            if sn.month != month:
                continue
            if account is not None:
                if sn.account_id == account:
                    total += sn.amount
                continue
            a = self.acc.get(sn.account_id)
            t, o, liq = (a.type, a.owner, a.liquidity) if a else ("?", "?", "?")
            if type_ is not None and t != type_:
                continue
            if not_type is not None and t == not_type:
                continue
            if liquidity is not None and liq != liquidity:
                continue
            if owner is not None and o != owner:
                continue
            if use_view and owner is None and not self.match(o):
                continue
            total += sn.amount
        return total

    # ------------------------------------------------------------ 손익
    def pnl(self) -> dict:
        def series(fn):
            return [fn(m) for m in self.months]

        cat = lambda name: series(lambda m: self.tx_cat[(m, name)])
        grp = lambda g: series(lambda m: self.tx_group[(m, g)])
        rows = {f"cat:{c.name}": cat(c.name) for c in self.ds.categories}
        for c in s.CATEGORY_TABLE:   # 기본 카테고리를 지운 경우에도 키가 있도록
            rows.setdefault(f"cat:{c[0]}", cat(c[0]))
        rows["income"] = grp(s.INCOME)
        rows["fixed"] = grp(s.FIXED)
        rows["variable"] = grp(s.VARIABLE)
        rows["irregular"] = grp(s.IRREGULAR)
        rows["capital"] = grp(s.CAPITAL)
        rows["uncategorized"] = grp(s.UNCATEGORIZED)
        rows["essential"] = series(lambda m: self.tx_ess[m])
        rows["consumption"] = [a + b + c for a, b, c in zip(rows["fixed"], rows["variable"], rows["irregular"])]
        rows["surplus"] = [i - c for i, c in zip(rows["income"], rows["consumption"])]
        rows["invest"] = [sum(rows[f"cat:{n}"][i] for n in s.INVEST_CATEGORIES) for i in range(12)]
        rows["net_cash"] = [a - b for a, b in zip(rows["surplus"], rows["capital"])]
        rows["saving_rate"] = [ratio(a, b) for a, b in zip(rows["surplus"], rows["income"])]

        agg = {}
        for key, values in rows.items():
            if key == "saving_rate":
                continue
            n = sum(values)
            agg[key] = {"N": n, "O": n / 12, "P": sum(values[-3:]) / 3, "M": values[-1]}
        for col in "NOPM":   # 비율은 합계끼리 나눈다 (평균내지 않음)
            agg.setdefault("saving_rate", {})[col] = ratio(agg["surplus"][col], agg["income"][col])
            agg.setdefault("fixed_ratio", {})[col] = ratio(agg["fixed"][col], agg["income"][col])
            agg.setdefault("invest_ratio", {})[col] = ratio(agg["invest"][col], agg["income"][col])
        return {"months": self.months, "rows": rows, "agg": agg}

    # ------------------------------------------------------------ 재무상태표
    def balance(self) -> dict:
        def block(month):
            types = {t: self.snap_sum(month, type_=t) for t in s.ASSET_TYPES}
            assets = sum(types.values())
            liab = self.snap_sum(month, type_=s.LIABILITY)
            emergency = self.snap_sum(month, type_="현금성", liquidity="즉시")
            return {
                "types": types, "assets": assets, "liabilities": liab, "net": assets - liab,
                "available_net": assets - liab - types["부동산"], "invest": types["투자"] + types["연금"],
                "debt_ratio": ratio(liab, assets), "emergency": emergency,
                "cash_available": emergency - self.snap_sum(month, type_=s.LIABILITY, liquidity="즉시"),
                "liquidity": {liq: self.snap_sum(month, liquidity=liq, not_type=s.LIABILITY) for liq in s.LIQUIDITY},
            }

        cur, prev = block(self.base), block(self.prev)
        members = []
        for m in s.OWNERS:
            assets = self.snap_sum(self.base, owner=m, not_type=s.LIABILITY, use_view=False)
            debt = self.snap_sum(self.base, owner=m, type_=s.LIABILITY, use_view=False)
            members.append({"member": m, "assets": assets, "debt": debt, "net": assets - debt,
                            "invest": self.snap_sum(self.base, owner=m, type_="투자", use_view=False)
                            + self.snap_sum(self.base, owner=m, type_="연금", use_view=False),
                            "cash": self.snap_sum(self.base, owner=m, type_="현금성", use_view=False)})
        trend = []
        for month in self.months:
            assets = self.snap_sum(month, not_type=s.LIABILITY)
            debt = self.snap_sum(month, type_=s.LIABILITY)
            trend.append({"month": month, "assets": assets, "debt": debt, "net": assets - debt,
                          "invest": self.snap_sum(month, type_="투자") + self.snap_sum(month, type_="연금"),
                          "cash": self.snap_sum(month, type_="현금성")})
        accounts = [{"id": a.id, "name": a.name, "type": a.type, "owner": a.owner,
                     "current": self.snap_sum(self.base, account=a.id), "previous": self.snap_sum(self.prev, account=a.id)}
                    for a in self.ds.accounts]
        return {"current": cur, "previous": prev, "members": members, "trend": trend, "accounts": accounts}

    # ------------------------------------------------------------ 예산
    def budget(self) -> dict:
        base_no = month_no(self.base)
        year_start = base_no // 100 * 100 + 1
        month_of_year = base_no % 100

        def actual(category: str, basis: str, member_ok) -> float:
            total = 0.0
            for t in self.ds.transactions:
                if t.category != category or not member_ok(t.member):
                    continue
                if basis == "연":
                    if year_start <= t.month_no <= base_no:
                        total += t.amount
                elif t.month == self.base:
                    total += t.amount
            return total

        rows = []
        for b in self.ds.budgets:
            if not b.category:
                continue
            c = self.cat.get(b.category)
            group = c.group if c else "?"
            period = b.amount * month_of_year / 12 if b.basis == "연" else b.amount
            act = actual(b.category, b.basis, self.match)
            rate = ratio(act, period) if period else None
            status = "" if not period else ("🔴 초과" if rate > 1 else
                                            "⚠ 주의" if rate >= 0.9 and group != s.FIXED else "✅ 양호")
            rows.append({"category": b.category, "group": group, "basis": b.basis, "budget": b.amount, "period_budget": period,
                         "actual": act, "rate": rate, "remaining": period - act, "status": status,
                         "by_member": {m: actual(b.category, b.basis, lambda x, m=m: x == m) for m in s.OWNERS}})
        totals = {}
        for basis in ("월", "연"):
            sel = [r for r in rows if r["basis"] == basis]
            e, f = sum(r["period_budget"] for r in sel), sum(r["actual"] for r in sel)
            g = ratio(f, e)
            totals[basis] = {"budget": sum(r["budget"] for r in sel), "period_budget": e, "actual": f, "rate": g,
                             "status": "" if e == 0 else "🔴 초과" if g > 1 else "⚠ 주의" if g >= 0.9 else "✅ 양호"}
        return {"rows": rows, "totals": totals, "over": [r for r in rows if "초과" in r["status"]]}

    # ------------------------------------------------------------ 투자
    def invest(self, pnl: dict, bal: dict) -> dict:
        holdings = []
        for h in self.ds.holdings:
            a = self.acc.get(h.account_id)
            owner = a.owner if a else "?"
            cost, value = h.qty * h.avg_price, h.qty * h.price
            holdings.append({"id": h.id, "account_id": h.account_id, "account": a.name if a else "?", "owner": owner, "name": h.name,
                             "code": h.code, "asset_class": h.asset_class, "qty": h.qty, "avg_price": h.avg_price,
                             "price": h.price, "cost": cost, "value": value, "gain": value - cost,
                             "return": ratio(value - cost, cost) if cost else None})
        mine = [h for h in holdings if self.match(h["owner"])]
        total = sum(h["value"] for h in mine)
        alloc = []
        for klass in s.ASSET_CLASSES:
            target = self.ds.allocation.get(klass, 0.0)
            value = sum(h["value"] for h in mine if h["asset_class"] == klass)
            cur = ratio(value, total)
            gap = cur - target
            status = "" if total == 0 else ("⚠ 리밸런싱" if abs(gap) > self.ds.settings.band else "✅ 적정")
            alloc.append({"asset_class": klass, "target": target, "value": value, "current": cur, "gap": gap,
                          "status": status, "adjust": target * total - value})
        base_no = month_no(self.base)
        year_start = base_no // 100 * 100 + 1

        def ytd(keyword: str) -> float:
            k = keyword.lower()
            return sum(t.amount for t in self.ds.transactions
                       if year_start <= t.month_no <= base_no and k in t.desc.lower() and self.match(t.member))

        st = self.ds.settings
        pension = ytd("연금저축")
        tax = [
            {"item": "연금저축", "limit": st.lim_pension, "paid": pension},
            {"item": "연금저축+IRP 합산", "limit": st.lim_pension_total, "paid": pension + ytd("IRP")},
            {"item": "ISA", "limit": st.lim_isa, "paid": ytd("ISA")},
        ]
        for t in tax:
            t["remaining"] = max(0, t["limit"] - t["paid"])
            t["used"] = ratio(t["paid"], t["limit"])
        target = st.invest_target(self.view)
        a = pnl["agg"]["invest"]
        return {
            "holdings": holdings, "allocation": alloc, "total_value": total,
            "total_cost": sum(h["cost"] for h in mine), "tax": tax,
            "contribution": {"month": a["M"], "target": target, "rate": ratio(a["M"], target), "last12": a["N"],
                             "avg": a["O"], "assets": bal["current"]["invest"], "assets_prev": bal["previous"]["invest"],
                             "est_return": bal["current"]["invest"] - bal["previous"]["invest"] - a["M"]},
        }

    # ------------------------------------------------------------ 부채
    def debt(self, pnl: dict) -> dict:
        rates = [d.rate for d in self.ds.debts if d.account_id]
        rows = []
        for d in self.ds.debts:
            if not d.account_id:
                continue
            a = self.acc.get(d.account_id)
            bal = self.snap_sum(self.base, account=d.account_id)
            months_left = None if d.maturity is None else max(0, int(xround((d.maturity - self.today).days / 30.4)))
            rows.append({"name": d.name, "account_id": d.account_id, "owner": a.owner if a else "?", "balance": bal,
                         "rate": d.rate, "maturity": d.maturity.isoformat() if d.maturity else None, "method": d.method,
                         "payment": d.payment, "interest": bal * d.rate / 12, "annual": d.payment * 12,
                         "plus1pt": bal * 0.01 / 12, "months_left": months_left,
                         "priority": 1 + sum(1 for r in rates if r > d.rate)})
        mine = [r for r in rows if self.match(r["owner"])]
        monthly = sum(r["payment"] for r in mine)
        if self.view == "공동":   # 공동 계좌는 소득이 거의 없어 가계 전체 소득으로 본다
            start, end = month_no(self.months[0]), month_no(self.base)
            income = sum(t.amount for t in self.ds.transactions if t.member and start <= t.month_no <= end
                         and (self.cat[t.category].group if t.category in self.cat else "") == s.INCOME)
        else:
            income = pnl["agg"]["income"]["N"]
        total_bal = sum(r["balance"] for r in rows)
        return {"rows": rows, "balance": sum(r["balance"] for r in mine), "monthly": monthly, "annual": monthly * 12,
                "income": income, "dsr": ratio(monthly * 12, income), "plus1pt": sum(r["plus1pt"] for r in mine),
                "avg_rate": ratio(sum(r["balance"] * r["rate"] for r in rows), total_bal)}

    # ------------------------------------------------------------ 목표
    def goals(self, pnl: dict) -> dict:
        st = self.ds.settings
        rows = []
        for g in self.ds.goals:
            target = g.target if g.target is not None else xround(st.t_emergency * pnl["agg"]["essential"]["P"], -4)
            current = sum(self.snap_sum(self.base, account=a) for a in g.accounts if a)
            progress = min(1, current / target) if target else None
            if g.start and g.end:
                plan = 1 if g.end <= g.start else max(0, min(1, (self.today - g.start).days / (g.end - g.start).days))
            else:
                plan = None
            if progress is None or plan is None:
                status = ""
            else:
                status = "🎉 달성" if progress >= 1 else "✅ 순항" if progress >= plan - st.goal_tol else "⚠ 지연"
            months_left = max(1, int(xround((g.end - self.today).days / 30.4))) if g.end else None
            rows.append({"name": g.name, "owner": g.owner, "target": target, "auto_target": g.target is None,
                         "start": g.start.isoformat() if g.start else None, "end": g.end.isoformat() if g.end else None,
                         "accounts": g.accounts, "current": current, "progress": progress, "plan": plan, "status": status,
                         "months_left": months_left,
                         "monthly_needed": max(0, (target - current) / months_left) if months_left else None,
                         "counted": min(current, target)})
        total_target = sum(r["target"] for r in rows)
        retire = next((r for r in rows if r["name"].startswith("노후")), None)
        return {"rows": rows, "weighted": ratio(sum(r["counted"] for r in rows), total_target),
                "retirement": (retire["progress"] or 0) if retire else 0,
                "delayed": [r for r in rows if "지연" in r["status"]],
                "monthly_needed": sum(r["monthly_needed"] or 0 for r in rows)}

    # ------------------------------------------------------------ 보험
    def insurance(self, pnl: dict) -> dict:
        matrix = []
        for member in ("본인", "배우자", "자녀"):
            row = {"member": member, "premium": sum(p.premium for p in self.ds.insurances if p.insured == member), "cells": {}}
            for cov in s.COVERAGES:
                amount = sum(p.coverages.get(cov, 0) or 0 for p in self.ds.insurances if p.insured == member)
                if member == "자녀" and cov == "사망":
                    row["cells"][cov] = {"amount": None, "text": "-"}
                else:
                    row["cells"][cov] = {"amount": amount,
                                         "text": f"✅ {won(amount / 10000)}만" if amount > 0 else "❌ 공백"}
            matrix.append(row)
        gaps = sum(1 for r in matrix for c in r["cells"].values() if "공백" in c["text"])
        premium = sum(p.premium for p in self.ds.insurances)
        income = pnl["agg"]["income"]["O"]
        return {"policies": len(self.ds.insurances), "matrix": matrix, "gaps": gaps, "premium": premium,
                "burden": ratio(premium, income)}

    # ------------------------------------------------------------ 일정·현금흐름
    def events(self) -> list[dict]:
        out = []
        for e in sorted(self.ds.events, key=lambda e: e.day):
            dday = (e.day - self.today).days
            out.append({"day": e.day.isoformat(), "desc": e.desc, "kind": e.kind, "amount": e.amount, "member": e.member,
                        "month": f"{e.day.year}-{e.day.month:02d}", "dday": dday,
                        "alert": f"{e.desc} D-{dday}" if 0 <= dday <= self.ds.settings.alert_days else ""})
        return out

    def cashflow(self, pnl: dict, bal: dict, events: list[dict]) -> dict:
        agg = pnl["agg"]
        start = bal["current"]["cash_available"]
        inflow = (agg["cat:급여"]["N"] + agg["cat:이자배당"]["N"] + agg["cat:부수입"]["N"]) / 12
        outflow = (agg["fixed"]["N"] + agg["variable"]["N"]) / 12
        capital = agg["capital"]["P"]
        rows, balance = [], start
        for k in range(1, 7):
            month = shift_month(self.base, k)
            ev_in = sum(e["amount"] for e in events if e["month"] == month and e["kind"] == "유입" and self.match(e["member"]))
            ev_out = sum(e["amount"] for e in events if e["month"] == month and e["kind"] == "유출" and self.match(e["member"]))
            net = inflow + ev_in - outflow - capital - ev_out
            balance += net
            rows.append({"month": month, "inflow": inflow, "event_in": ev_in, "outflow": outflow, "capital": capital,
                         "event_out": ev_out, "net": net, "balance": balance,
                         "status": "🔴 부족" if balance < self.ds.settings.min_cash else "✅ 정상"})
        return {"start": start, "inflow": inflow, "outflow": outflow, "capital": capital,
                "min_cash": self.ds.settings.min_cash, "rows": rows}

    # ------------------------------------------------------------ 대시보드
    def dashboard(self) -> dict:
        st = self.ds.settings
        pnl = self.pnl()
        bal = self.balance()
        bud = self.budget()
        inv = self.invest(pnl, bal)
        debt = self.debt(pnl)
        goals = self.goals(pnl)
        ins = self.insurance(pnl)
        events = self.events()
        cash = self.cashflow(pnl, bal, events)
        agg, cur, prev = pnl["agg"], bal["current"], bal["previous"]
        joint = self.view == "공동"
        invest_target = st.invest_target(self.view)
        essential = agg["essential"]["P"]
        emergency_months = ratio(cur["emergency"], essential)
        monthly = bud["totals"]["월"]
        over = len(bud["over"])
        net_change = cur["net"] - prev["net"]
        inv_change = cur["invest"] - prev["invest"]
        saving = agg["saving_rate"]["M"]
        invest_paid = agg["invest"]["M"]
        delayed = len(goals["delayed"])

        cards = [
            Card("net", "순자산", cur["net"], "won", f"약 {xround(cur['net'] / 1e8, 2):.2f}억원",
                 ("✅ 전월 대비 증가 " if net_change >= 0 else "⚠ 전월 대비 감소 ") + signed_won(net_change)),
            Card("saving", "저축률 (이번 달)", None if joint else saving, "pct",
                 "공동 보기는 직접 소득이 없어 계산하지 않음" if joint
                 else f"목표 {pct0(st.t_saving)} · 12개월 {pct1(agg['saving_rate']['N'])}",
                 "- 해당 없음" if joint else "- 소득 데이터 없음" if agg["income"]["M"] == 0
                 else "✅ 달성" if saving >= st.t_saving else "⚠ 미달"),
            Card("invest_paid", "월 투자 납입액", invest_paid, "won",
                 f"목표 {won(invest_target)}" + ("" if joint else f" · 납입률 {pct0(agg['invest_ratio']['M'])}"),
                 "✅ 달성" if invest_paid >= invest_target else f"⚠ 미달 {won(invest_target - invest_paid)}"),
            Card("invest_assets", "투자+연금 자산", cur["invest"], "won", f"총자산의 {pct1(ratio(cur['invest'], cur['assets']))}",
                 ("✅ 증가 " if inv_change >= 0 else "⚠ 감소 ") + signed_won(inv_change)),
            Card("budget", "소비 예산 집행률", monthly["rate"], "pct",
                 f"실적 {won(monthly['actual'])} / 예산 {won(monthly['period_budget'])}" if self.view == "전체"
                 else f"가계 예산 중 {self.view} 사용분 {won(monthly['actual'])}",
                 f"🔴 초과 카테고리 {over}개" if over else "⚠ 주의" if monthly["rate"] >= 0.9 else "✅ 양호"),
            Card("emergency", "비상자금", emergency_months, "months",
                 f"목표 {st.t_emergency:g}개월 · {won(cur['emergency'])}원",
                 "✅ 달성" if emergency_months >= st.t_emergency else "⚠ 미달"),
            Card("debt_ratio", "부채비율", cur["debt_ratio"], "pct",
                 f"상한 {pct0(st.t_debt)} · 부채 {xround(cur['liabilities'] / 1e8, 2):.2f}억",
                 "✅ 양호" if cur["debt_ratio"] <= st.t_debt else "⚠ 주의"),
            Card("dsr", "DSR", debt["dsr"], "pct", f"상한 {pct0(st.t_dsr)} · 월 원리금 {won(debt['monthly'])}",
                 "✅ 양호" if debt["dsr"] <= st.t_dsr else "⚠ 주의"),
            Card("goals", "목표 달성률 (가중)", goals["weighted"], "pct", f"노후 준비율 {pct0(goals['retirement'])}",
                 "✅ 모두 순항" if delayed == 0 else f"⚠ 지연 {delayed}건"),
            Card("fi", "재무자립도", ratio(agg["cat:이자배당"]["O"], agg["consumption"]["O"]), "pct",
                 f"월 수동소득 {won(agg['cat:이자배당']['O'])}원", "장기 목표 100% (수동소득 ≥ 생활비)"),
        ]

        alerts = []
        if over:
            alerts.append("🔴 예산 초과: " + ", ".join(f"{r['category']} {pct0(r['rate'])}" for r in bud["over"]))
        if not joint and agg["income"]["M"] > 0 and saving < st.t_saving:
            alerts.append(f"⚠ 저축률 {pct1(saving)} — 목표 {pct0(st.t_saving)} 미달")
        if invest_paid < invest_target:
            alerts.append(f"⚠ 투자 납입 {won(invest_target - invest_paid)}원 부족 (목표 {won(invest_target)})")
        if essential > 0 and emergency_months < st.t_emergency:
            alerts.append(f"⚠ 비상자금 {xround(emergency_months, 1):.1f}개월 — 목표까지 "
                          f"{won((st.t_emergency - emergency_months) * essential)}원 더 필요")
        rebal = [a for a in inv["allocation"] if "리밸런싱" in a["status"]]
        if self.view == "전체" and rebal:
            alerts.append("⚖ 리밸런싱 검토: " + ", ".join(f"{a['asset_class']} {signed_pct0(a['gap'])}" for a in rebal))
        if cur["debt_ratio"] > st.t_debt or debt["dsr"] > st.t_dsr:
            alerts.append(f"⚠ 부채 관리: 부채비율 {pct0(cur['debt_ratio'])} · DSR {pct0(debt['dsr'])}")
        upcoming = [e["alert"] for e in self.ds_event_order(events) if e["alert"]]
        if upcoming:
            alerts.append("🗓 다가오는 일정: " + ", ".join(upcoming))
        if delayed:
            alerts.append("🎯 목표 지연: " + ", ".join(f"{g['name']} {pct0(g['progress'])}" for g in goals["delayed"]))
        short = [r for r in cash["rows"] if "부족" in r["status"]]
        if cash["inflow"] > 0 and short:
            alerts.append("🔴 잔고 부족 예상: " + ", ".join(f"{r['month']} {won(r['balance'])}원" for r in short))
        if ins["policies"] and ins["gaps"]:
            alerts.append(f"🛡 보장 공백 {ins['gaps']}건 — 보험 탭 확인")
        if agg["uncategorized"]["M"] > 0:
            alerts.append(f"❓ 미분류 거래 {won(agg['uncategorized']['M'])}원 — 카테고리 지정 필요")

        return {
            "base_month": self.base, "view": self.view, "today": self.today.isoformat(),
            "cards": [c.__dict__ for c in cards], "alerts": alerts,
            "pnl": pnl, "balance": bal, "budget": bud, "invest": inv, "debt": debt, "goals": goals,
            "insurance": ins, "events": events, "cashflow": cash,
        }

    def ds_event_order(self, events: list[dict]) -> list[dict]:
        """스프레드시트는 일정 시트에 입력된 순서대로 알림을 잇는다."""
        order = {(e.day.isoformat(), e.desc): i for i, e in enumerate(self.ds.events)}
        return sorted(events, key=lambda e: order.get((e["day"], e["desc"]), 0))


def compute(ds: Dataset, view: str = "전체", base_month: str | None = None, today: date | None = None) -> dict:
    return Engine(ds, view, base_month, today).dashboard()
