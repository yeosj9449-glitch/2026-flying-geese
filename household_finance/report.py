"""월간 결산 리포트 - 메일 본문(HTML·텍스트)과 메일 발송.

웹앱의 '결산 리포트' 화면과 같은 내용을 서버에서 만든다. 메일 앱에서도 깨지지 않도록 표와
인라인 스타일만 쓴다. 발송 설정은 환경변수로 받는다 (비밀번호를 DB나 코드에 남기지 않기 위해):

    HH_SMTP_HOST      예: smtp.gmail.com
    HH_SMTP_PORT      587(STARTTLS, 기본) 또는 465(SSL)
    HH_SMTP_USER      로그인 아이디 (보통 메일 주소)
    HH_SMTP_PASSWORD  비밀번호 - Gmail은 '앱 비밀번호'를 만들어 넣는다
    HH_MAIL_FROM      보내는 주소 (기본: HH_SMTP_USER)
    HH_MAIL_TO        받는 주소, 쉼표로 여러 명 (예: 본인@메일, 배우자@메일)
"""

from __future__ import annotations

import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from html import escape

from household_finance.engine import won


def _pct(x, d=1) -> str:
    return "—" if x is None else f"{x * 100:.{d}f}%"


def _short(x: float) -> str:
    a, s = abs(x), "-" if x < 0 else ""
    if a >= 1e8:
        return s + f"{a / 1e8:.2f}".rstrip("0").rstrip(".") + "억"
    if a >= 1e4:
        return s + f"{round(a / 1e4):,}만"
    return s + f"{round(a):,}"


def _signed(x: float) -> str:
    return ("+" if x >= 0 else "") + won(x)


def _clean(s: str) -> str:
    """알림 문구 앞의 기호(🔴 ⚠ 등) 제거."""
    i = 0
    while i < len(s) and not (s[i].isalnum() or s[i] in "+-"):
        i += 1
    return s[i:].strip()


def _tone(status: str) -> str:
    if any(k in status for k in ("🔴", "❌", "초과", "부족", "공백")):
        return "#b42318"
    if any(k in status for k in ("⚠", "⚖", "미달", "지연", "주의", "리밸런싱", "감소")):
        return "#9a6400"
    if any(k in status for k in ("✅", "🎉", "달성", "양호", "순항", "정상", "증가", "적정")):
        return "#1f7a4d"
    return "#5f6878"


def _value(card: dict) -> str:
    v = card["value"]
    if v is None:
        return "—"
    return {"won": f"{won(v)}원", "months": f"{v:.1f}개월"}.get(card["format"], _pct(v))


def build(d: dict) -> tuple[str, str, str]:
    """엔진의 대시보드 결과 → (제목, HTML 본문, 텍스트 본문)."""
    month = d["base_month"]
    title_month = f"{month[:4]}년 {int(month[5:])}월"
    rows, agg = d["pnl"]["rows"], d["pnl"]["agg"]
    cur, prev = d["balance"]["current"], d["balance"]["previous"]
    i = len(rows["income"]) - 1
    prev_month = d["pnl"]["months"][i - 1]
    subject = f"[우리집 주식회사] {title_month} 월간 결산 · 알림 {len(d['alerts'])}건"
    summary = (f"순자산 {won(cur['net'])}원(전월 대비 {_signed(cur['net'] - prev['net'])}원), "
               f"저축률 {_pct(rows['saving_rate'][i])}, 투자 납입 {won(rows['invest'][i])}원. 점검 알림 {len(d['alerts'])}건.")
    over = [r for r in d["budget"]["rows"] if "초과" in r["status"]]
    upcoming = [e for e in d["events"] if 0 <= e["dday"] <= 62]
    todo = [_clean(a) for a in d["alerts"] if not a.startswith("🗓")] + \
           [f"{e['day']} {e['desc']}" + (f" ({e['kind']} {won(e['amount'])}원)" if e["amount"] else "") for e in upcoming]

    th = 'style="text-align:{a};font-size:12px;color:#5f6878;font-weight:500;padding:6px 8px;border-bottom:1px solid #e1e5ec"'
    td = 'style="text-align:{a};padding:6px 8px;border-bottom:1px solid #eef1f6;font-variant-numeric:tabular-nums"'

    def table(head: list[str], body: list[list[str]], raw_cols: set[int] = frozenset()) -> str:
        hs = "".join(f"<th {th.format(a='left' if j == 0 else 'right')}>{escape(x)}</th>" for j, x in enumerate(head))
        bs = "".join("<tr>" + "".join(
            f"<td {td.format(a='left' if j == 0 else 'right')}>{c if j in raw_cols else escape(c)}</td>" for j, c in enumerate(r)) + "</tr>"
            for r in body)
        return f'<table cellspacing="0" cellpadding="0" style="width:100%;border-collapse:collapse;margin:6px 0 4px">{hs and "<tr>" + hs + "</tr>"}{bs}</table>'

    def status(s: str) -> str:
        return f'<span style="color:{_tone(s)};font-weight:600">{escape(_clean(s))}</span>'

    h2 = lambda x: f'<h3 style="font-size:15px;margin:22px 0 4px;color:#1d2433">{escape(x)}</h3>'
    pnl_line = lambda label, k, is_pct=False: [label, *([_pct(rows[k][i]), _pct(rows[k][i - 1]), _pct(agg["saving_rate"]["N"])] if is_pct
                                                      else [won(rows[k][i]), won(rows[k][i - 1]), won(agg[k]["O"])])]
    parts = [
        f'<div style="font-family:Apple SD Gothic Neo,Malgun Gothic,sans-serif;color:#1d2433;max-width:720px;margin:0 auto;font-size:14px;line-height:1.5">',
        f'<p style="font-size:12px;color:#5f6878;margin:0">작성 {escape(d["today"])} · 기준 {title_month} 말</p>',
        f'<h2 style="font-size:20px;margin:4px 0 8px">우리집 주식회사 {title_month} 월간 결산</h2>',
        f"<p>{escape(summary)}</p>",
        h2("1. 핵심 지표"),
        table(["지표", "값", "참고", "상태"], [[c["label"], _value(c), c["note"], status(c["status"])] for c in d["cards"]], {3}),
        h2("2. 손익 (이번 달 · 전월 · 12개월 평균)"),
        table(["항목", title_month, f"{prev_month[:4]}년 {int(prev_month[5:])}월", "12개월 평균"], [
            pnl_line("소득", "income"), pnl_line("고정비", "fixed"), pnl_line("변동비", "variable"), pnl_line("비정기비", "irregular"),
            pnl_line("소비지출 합계", "consumption"), pnl_line("잉여 (소득-소비)", "surplus"), pnl_line("저축률", "saving_rate", True),
            pnl_line("투자 납입", "invest")]),
        h2("3. 재무상태 (월말 잔액)"),
        table(["항목", "이번 달", "전월", "증감"], [[label, won(cur[k]), won(prev[k]), _signed(cur[k] - prev[k])] for label, k in
                                               [("총자산", "assets"), ("총부채", "liabilities"), ("순자산", "net"), ("투자+연금", "invest"),
                                                ("비상자금(즉시 현금)", "emergency")]]),
        table(["구성원", "자산", "부채", "순자산"], [[m["member"], won(m["assets"]), won(m["debt"]), won(m["net"])] for m in d["balance"]["members"]]),
        h2("4. 예산 통제"),
        table(["초과 카테고리", "예산", "실적", "집행률"], [[r["category"], won(r["period_budget"]), won(r["actual"]), _pct(r["rate"], 0)] for r in over])
        if over else "<p>예산을 넘은 카테고리가 없습니다.</p>",
        h2("5. 목표 진척"),
        table(["목표", "현재 / 목표", "진척률", "필요 월적립", "상태"],
              [[g["name"], f"{_short(g['current'])} / {_short(g['target'])}", f"{_pct(g['progress'], 0)} (계획 {_pct(g['plan'], 0)})",
                "-" if g["monthly_needed"] is None else f"{won(g['monthly_needed'])}원", status(g["status"])] for g in d["goals"]["rows"]], {4}),
        h2("6. 다음 달 할 일"),
        "<ul style=\"padding-left:18px;margin:4px 0\">" + "".join(f"<li>{escape(x)}</li>" for x in todo) + "</ul>" if todo else "<p>없음</p>",
        '<p style="font-size:12px;color:#5f6878;margin-top:24px">이 메일은 우리집 주식회사 웹앱이 자동으로 보냈습니다. '
        "자세한 내용은 웹앱의 대시보드와 결산 리포트에서 확인하세요.</p></div>",
    ]
    text = "\n".join([subject, "", summary, "", "[핵심 지표]",
                      *[f"- {c['label']}: {_value(c)} ({_clean(c['status'])})" for c in d["cards"]],
                      "", "[다음 달 할 일]", *[f"- {x}" for x in todo]])
    return subject, "".join(parts), text


# ---------------------------------------------------------------- 메일 발송
@dataclass
class MailConfig:
    host: str
    port: int
    user: str
    password: str
    sender: str
    to: list[str]

    @classmethod
    def from_env(cls, env=os.environ) -> MailConfig | None:
        host, to = env.get("HH_SMTP_HOST"), [x.strip() for x in env.get("HH_MAIL_TO", "").split(",") if x.strip()]
        if not host or not to:
            return None
        user = env.get("HH_SMTP_USER", "")
        return cls(host, int(env.get("HH_SMTP_PORT", "587")), user, env.get("HH_SMTP_PASSWORD", ""), env.get("HH_MAIL_FROM") or user, to)


def send(cfg: MailConfig, subject: str, html: str, text: str, smtp_factory=None) -> None:
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, cfg.sender, ", ".join(cfg.to)
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    context = ssl.create_default_context()
    if smtp_factory is None:
        smtp_factory = (lambda: smtplib.SMTP_SSL(cfg.host, cfg.port, context=context, timeout=20)) if cfg.port == 465 \
            else (lambda: smtplib.SMTP(cfg.host, cfg.port, timeout=20))
    with smtp_factory() as smtp:
        if cfg.port != 465:
            smtp.starttls(context=context)
        if cfg.user:
            smtp.login(cfg.user, cfg.password)
        smtp.send_message(msg)
