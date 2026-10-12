"""'우리집 주식회사' 자산관리 스프레드시트 생성기.

모든 보고 수치는 엑셀 수식으로 계산된다 - 입력 시트(거래내역·스냅샷 등)를 바꾸면
대시보드까지 자동으로 다시 계산된다. 구글 시트로 가져가도 그대로 동작하도록
Excel 2007 계열 함수(SUMIFS, INDEX/MATCH, TEXTJOIN)만 사용한다.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.comments import Comment
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import column_index_from_string, get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from household_finance import schema as s

# ---------------------------------------------------------------- 스타일
FONT_NAME = "맑은 고딕"
NAVY = "1F2A44"
INPUT_BLUE = "0000FF"
MONEY = '#,##0;[Red]-#,##0;"-"'
PCT = '0.0%;[Red]-0.0%;"-"'
DATE_FMT = "yyyy-mm-dd"

F_BASE = Font(name=FONT_NAME, size=10)
F_INPUT = Font(name=FONT_NAME, size=10, color=INPUT_BLUE)
F_BOLD = Font(name=FONT_NAME, size=10, bold=True)
F_HEADER = Font(name=FONT_NAME, size=10, bold=True, color="FFFFFF")
F_TITLE = Font(name=FONT_NAME, size=16, bold=True, color=NAVY)
F_SECTION = Font(name=FONT_NAME, size=11, bold=True, color=NAVY)
F_NOTE = Font(name=FONT_NAME, size=9, italic=True, color="666666")
FILL_HEADER = PatternFill("solid", fgColor=NAVY)
FILL_INPUT_HEADER = PatternFill("solid", fgColor="2F5597")
FILL_KEY = PatternFill("solid", fgColor="FFFF00")
FILL_SECTION = PatternFill("solid", fgColor="E8ECF4")
FILL_TOTAL = PatternFill("solid", fgColor="F2F2F2")
FILL_CARD = PatternFill("solid", fgColor="F7F9FC")
THIN = Side(style="thin", color="D0D5DD")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
LEFT = Alignment(horizontal="left", vertical="center", wrap_text=False)

TAB_COLORS = {"dashboard": "1F2A44", "guide": "7F7F7F", "input": "2F5597", "report": "548235", "master": "BF8F00"}


def q(sheet: str) -> str:
    """시트 참조 접두어 - 한글 시트명은 항상 작은따옴표로 감싼다."""
    return f"'{sheet}'!"


# 설정 시트의 고정 셀 (모든 수식이 여기를 바라본다)
SET = {
    "base": "$B$3", "view": "$B$4", "crit": "$B$5", "prev": "$B$6", "basenum": "$B$7",
    "yearstart": "$B$8", "monthno": "$B$9", "today": "$B$10",
    "t_saving": "$B$12", "t_emergency": "$B$13", "t_debt": "$B$14", "t_dsr": "$B$15",
    "band": "$B$16", "t_invest": "$B$17", "min_cash": "$B$18", "alert_days": "$B$19",
    "goal_tol": "$B$20", "lim_pension_total": "$B$22", "lim_pension": "$B$23", "lim_isa": "$B$24",
    "t_invest_view": "$B$29",   # 현재 보기(전체/본인/배우자/공동)에 맞는 월 투자 납입 목표
}


def S(key: str) -> str:
    return q(s.SETTINGS) + SET[key]


def tx(col_name: str) -> str:
    letter = s.col_letter(s.TX_COLUMNS, col_name)
    return f"{q(s.TX)}${letter}$2:${letter}${s.TX_MAX_ROW}"


def snap(col_name: str) -> str:
    letter = s.col_letter(s.SNAPSHOT_COLUMNS, col_name)
    return f"{q(s.SNAPSHOT)}${letter}$2:${letter}${s.SNAPSHOT_MAX_ROW}"


# ---------------------------------------------------------------- 공통 도우미
def style_header(ws, row: int, first_col: int, last_col: int, input_sheet: bool = False) -> None:
    for c in range(first_col, last_col + 1):
        cell = ws.cell(row=row, column=c)
        cell.font = F_HEADER
        cell.fill = FILL_INPUT_HEADER if input_sheet else FILL_HEADER
        cell.alignment = CENTER
        cell.border = BOX


def write_header(ws, row: int, headers: list[str], first_col: int = 1, input_sheet: bool = False) -> None:
    for i, h in enumerate(headers):
        ws.cell(row=row, column=first_col + i, value=h)
    style_header(ws, row, first_col, first_col + len(headers) - 1, input_sheet)


def title(ws, text: str, note: str = "") -> None:
    ws["A1"] = text
    ws["A1"].font = F_TITLE
    if note:
        ws["A2"] = note
        ws["A2"].font = F_NOTE


def section(ws, row: int, text: str, first_col: int = 1, last_col: int = 6) -> None:
    cell = ws.cell(row=row, column=first_col, value=text)
    cell.font = F_SECTION
    for c in range(first_col, last_col + 1):
        ws.cell(row=row, column=c).fill = FILL_SECTION


def widths(ws, values: dict[str, float]) -> None:
    for letter, w in values.items():
        ws.column_dimensions[letter].width = w


def put(ws, ref: str, value, fmt: str | None = None, font: Font | None = None, fill=None, border=True, align=None):
    cell = ws[ref]
    cell.value = value
    cell.font = font or F_BASE
    if fmt:
        cell.number_format = fmt
    if fill:
        cell.fill = fill
    if border:
        cell.border = BOX
    if align:
        cell.alignment = align
    return cell


def add_list_validation(ws, cell_range: str, source: str) -> None:
    dv = DataValidation(type="list", formula1=source.lstrip("="), allow_blank=True, showDropDown=False)
    dv.error = "목록에서 선택하세요."
    dv.errorTitle = "입력 확인"
    ws.add_data_validation(dv)
    dv.add(cell_range)


def status_colors(ws, cell_range: str) -> None:
    """상태 텍스트에 신호등 색을 입힌다 (🔴/❌=빨강, ⚠=주황, ✅/🎉=초록)."""
    first = cell_range.split(":")[0].replace("$", "")
    rules = [
        (["초과", "부족", "공백"], "FDE2E1", "9B1C1C"),
        (["주의", "미달", "지연", "리밸런싱", "감소"], "FEF3C7", "92400E"),
        (["양호", "달성", "순항", "정상", "증가", "보장", "적정"], "DCFCE7", "166534"),
    ]
    for words, bg, fg in rules:
        cond = "OR(" + ",".join(f'ISNUMBER(SEARCH("{w}",{first}))' for w in words) + ")"
        ws.conditional_formatting.add(
            cell_range,
            FormulaRule(formula=[cond], fill=PatternFill("solid", fgColor=bg), font=Font(color=fg, bold=True)),
        )


def month_offset(k: int) -> str:
    """기준월로부터 k개월 떨어진 달 (yyyy-mm 텍스트)."""
    return f'TEXT(EDATE(DATEVALUE({S("base")}&"-01"),{k}),"yyyy-mm")'


# ---------------------------------------------------------------- 설정
def build_settings(ws, st) -> None:
    title(ws, "⚙ 설정", "노란 칸은 가정의 목표치(경영 목표)입니다. 기준월·보기는 대시보드 상단에서 바꿉니다.")
    write_header(ws, 2, ["항목", "값", "설명"])
    rows = [
        (3, "기준월", f"=IF(ISNUMBER({q(s.DASHBOARD)}$C$4),TEXT({q(s.DASHBOARD)}$C$4,\"yyyy-mm\"),TRIM({q(s.DASHBOARD)}$C$4))", None, "대시보드 C4에서 입력 (yyyy-mm)"),
        (4, "보기 구성원", f"={q(s.DASHBOARD)}$E$4", None, "대시보드 E4에서 선택"),
        (5, "조회 조건", '=IF(B4="전체","*",B4)', None, "내부 계산용 (전체 = 모든 구성원)"),
        (6, "전월", '=TEXT(EDATE(DATEVALUE(B3&"-01"),-1),"yyyy-mm")', None, "내부 계산용"),
        (7, "기준월 번호", '=VALUE(SUBSTITUTE(B3,"-",""))', "0", "내부 계산용 (예: 202609)"),
        (8, "연초 번호", "=INT(B7/100)*100+1", "0", "내부 계산용 (예: 202601)"),
        (9, "기준월(월)", "=MOD(B7,100)", "0", "비정기비 연간 예산 안분용"),
        (10, "오늘", "=TODAY()", DATE_FMT, "일정 D-day·목표 계획 진척률 계산"),
    ]
    for r, label, value, fmt, desc in rows:
        put(ws, f"A{r}", label)
        put(ws, f"B{r}", value, fmt)
        put(ws, f"C{r}", desc, font=F_NOTE)
    section(ws, 11, "경영 목표 (KPI 기준값)", 1, 3)
    targets = [
        (12, "목표 저축률", st.t_saving, PCT, "(소득-소비지출)/소득. 일반적 권장 30% 이상"),
        (13, "비상자금 목표(개월)", st.t_emergency, '0"개월"', "필수지출 몇 개월분을 즉시 현금으로 보유할지"),
        (14, "부채비율 상한", st.t_debt, PCT, "총부채/총자산"),
        (15, "DSR 상한", st.t_dsr, PCT, "연간 원리금/연소득 (가정 자체 목표)"),
        (16, "리밸런싱 밴드", st.band, PCT, "목표 비중에서 ±이 값 이상 벗어나면 알림"),
        (18, "최소 유지잔고", st.min_cash, MONEY, "예상 가용현금이 이 아래로 내려가면 경고"),
        (19, "일정 알림 일수", st.alert_days, '0"일"', "며칠 전부터 일정을 알릴지"),
        (20, "목표 지연 허용폭", st.goal_tol, PCT, "계획 진척률보다 이만큼 뒤처지면 '지연'"),
    ]
    for r, label, value, fmt, desc in targets:
        put(ws, f"A{r}", label)
        put(ws, f"B{r}", value, fmt, font=F_INPUT, fill=FILL_KEY)
        put(ws, f"C{r}", desc, font=F_NOTE)
    put(ws, "A17", "월 투자 납입 목표 (가계 합계)")
    put(ws, "B17", "=SUM(B26:B28)", MONEY)
    put(ws, "C17", "투자이체+연금납입 합계 목표 = 아래 구성원별 목표의 합 (투자금 확대 핵심 지표)", font=F_NOTE)
    section(ws, 21, "절세 계좌 연간 한도 (세법 개정 시 수정)", 1, 3)
    limits = [
        (22, "연금계좌 세액공제 한도(합산)", st.lim_pension_total, "연금저축+IRP 합산 세액공제 대상 한도"),
        (23, "연금저축 세액공제 한도", st.lim_pension, "연금저축 단독 한도"),
        (24, "ISA 연간 납입한도", st.lim_isa, "ISA 연간 납입 한도"),
    ]
    for r, label, value, desc in limits:
        put(ws, f"A{r}", label)
        put(ws, f"B{r}", value, MONEY, font=F_INPUT, fill=FILL_KEY)
        put(ws, f"C{r}", desc, font=F_NOTE)
    section(ws, 25, "구성원별 월 투자 납입 목표 (부부가 각자 책임지는 몫)", 1, 3)
    for r, (member, value) in zip(range(26, 29), [(m, st.invest_targets.get(m, 0)) for m in s.OWNERS]):
        put(ws, f"A{r}", f"월 투자 납입 목표 - {member}")
        put(ws, f"B{r}", value, MONEY, font=F_INPUT, fill=FILL_KEY)
        put(ws, f"C{r}", f"{member} 보기에서 비교하는 목표", font=F_NOTE)
    put(ws, "A29", "현재 보기의 투자 목표")
    put(ws, "B29", '=IF(B4="본인",B26,IF(B4="배우자",B27,IF(B4="공동",B28,B17)))', MONEY)
    put(ws, "C29", "내부 계산용 - 대시보드·투자 시트가 이 값과 비교", font=F_NOTE)

    # 드롭다운 원본 목록
    lists = [("E", "구성원", s.MEMBERS), ("F", "보기", s.VIEW_OPTIONS), ("G", "계좌유형", s.ACCOUNT_TYPES),
             ("H", "유동성", s.LIQUIDITY), ("I", "자산군", s.ASSET_CLASSES), ("J", "예산기준", ["월", "연"]),
             ("K", "일정구분", s.EVENT_KINDS), ("L", "소유", s.OWNERS)]
    for col, head, values in lists:
        put(ws, f"{col}2", head, font=F_HEADER, fill=FILL_HEADER, align=CENTER)
        for i, v in enumerate(values):
            put(ws, f"{col}{3 + i}", v)
    widths(ws, {"A": 26, "B": 16, "C": 52, "D": 3, **{c: 11 for c in "EFGHIJKL"}})
    ws.freeze_panes = "A3"


# ---------------------------------------------------------------- 기준 정보
def build_categories(ws, categories) -> None:
    write_header(ws, 1, ["카테고리", "대분류", "필수지출(Y/N)", "설명"], input_sheet=True)
    notes = {s.CAPITAL: "소비 아님 - 자산 간 이동", s.IRREGULAR: "연간 예산으로 관리"}
    for i, (name, group, essential) in enumerate(((c.name, c.group, c.essential) for c in categories), start=2):
        for c, v in enumerate([name, group, essential, notes.get(group, "")], start=1):
            put(ws, f"{get_column_letter(c)}{i}", v, font=F_INPUT if c < 4 else F_NOTE)
    add_list_validation(ws, "B2:B200", '"' + ",".join(s.GROUPS) + '"')
    add_list_validation(ws, "C2:C200", '"Y,N"')
    widths(ws, {"A": 16, "B": 12, "C": 14, "D": 30})
    ws.freeze_panes = "A2"


def build_rules(ws, rules) -> None:
    write_header(ws, 1, ["키워드(내용에 포함)", "카테고리", "설명"], input_sheet=True)
    put(ws, "C2", "CSV 가져오기 시 위에서부터 먼저 맞는 규칙으로 자동 분류됩니다. 대소문자 무시.", font=F_NOTE, border=False)
    for i, (kw, cat) in enumerate(rules, start=2):
        put(ws, f"A{i}", kw, font=F_INPUT)
        put(ws, f"B{i}", cat, font=F_INPUT)
    add_list_validation(ws, "B2:B500", f"={q(s.CATEGORIES)}$A$2:$A$200")
    widths(ws, {"A": 22, "B": 16, "C": 70})
    ws.freeze_panes = "A2"


# ---------------------------------------------------------------- 입력 시트
def build_accounts(ws, accounts: list[tuple]) -> None:
    write_header(ws, 1, s.ACCOUNT_COLUMNS, input_sheet=True)
    for r, acc in enumerate(accounts, start=2):
        for c, v in enumerate(acc, start=1):
            put(ws, f"{get_column_letter(c)}{r}", v, font=F_INPUT)
    last = s.ACCOUNT_ROWS + 1
    add_list_validation(ws, f"D2:D{last}", f"={q(s.SETTINGS)}$G$3:$G$8")
    add_list_validation(ws, f"E2:E{last}", f"={q(s.SETTINGS)}$L$3:$L$5")
    add_list_validation(ws, f"F2:F{last}", f"={q(s.SETTINGS)}$H$3:$H$5")
    ws["I1"] = "유형: 현금성/투자/연금/부동산/기타자산/부채 · 유동성: 즉시(오늘 꺼낼 수 있음)/1년내/장기"
    ws["I1"].font = F_NOTE
    widths(ws, {"A": 9, "B": 20, "C": 16, "D": 10, "E": 9, "F": 9, "G": 26})
    ws.freeze_panes = "A2"


def build_snapshot(ws, rows: list[tuple]) -> None:
    write_header(ws, 1, s.SNAPSHOT_COLUMNS, input_sheet=True)
    for c in range(4, 8):
        ws.cell(row=1, column=c).fill = FILL_HEADER   # 수식 열은 짙은 색 헤더
    for r, (month, acc_id, amount) in enumerate(rows, start=2):
        put(ws, f"A{r}", month, "@", font=F_INPUT)
        put(ws, f"B{r}", acc_id, font=F_INPUT)
        put(ws, f"C{r}", amount, MONEY, font=F_INPUT)
        for name, formula in s.snapshot_row_formulas(r).items():
            put(ws, f"{s.col_letter(s.SNAPSHOT_COLUMNS, name)}{r}", formula)
    add_list_validation(ws, f"B2:B{s.SNAPSHOT_MAX_ROW}", f"={q(s.ACCOUNTS)}$A$2:$A${s.ACCOUNT_ROWS + 1}")
    ws["I1"] = "매월 말 계좌별 잔액을 기록 (부채도 양수로). `python -m household_finance new-month`로 다음 달 행을 자동 생성."
    ws["I1"].font = F_NOTE
    widths(ws, {"A": 10, "B": 9, "C": 16, "D": 20, "E": 10, "F": 9, "G": 9})
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:G{max(2, len(rows) + 1)}"


def write_tx_row(ws, r: int, t) -> None:
    """거래 한 행 기록 - 가져오기 도구(importer)도 이 함수를 쓴다."""
    values = {"일자": t.day, "내용": t.desc, "금액": t.amount, "카테고리": t.category,
              "구성원": t.member, "결제수단": t.payment, "출처": t.source, "메모": getattr(t, "memo", "")}
    formulas = s.tx_row_formulas(r)
    for name in s.TX_COLUMNS:
        ref = f"{s.col_letter(s.TX_COLUMNS, name)}{r}"
        if name in formulas:
            put(ws, ref, formulas[name], "0" if name == "월번호" else None)
        else:
            fmt = DATE_FMT if name == "일자" else MONEY if name == "금액" else None
            put(ws, ref, values[name], fmt, font=F_INPUT)


def build_transactions(ws, txs: list) -> None:
    write_header(ws, 1, s.TX_COLUMNS, input_sheet=True)
    for name in s.TX_FORMULA_COLUMNS:
        ws[f"{s.col_letter(s.TX_COLUMNS, name)}1"].fill = FILL_HEADER
    for r, t in enumerate(txs, start=2):
        write_tx_row(ws, r, t)
    add_list_validation(ws, f"E2:E{s.TX_MAX_ROW}", f"={q(s.CATEGORIES)}$A$2:$A$200")
    add_list_validation(ws, f"H2:H{s.TX_MAX_ROW}", f"={q(s.SETTINGS)}$L$3:$L$5")
    ws["N1"] = "금액은 항상 양수. 들어온 돈/나간 돈 구분은 카테고리의 대분류(소득·고정비…)가 결정합니다."
    ws["N1"].font = F_NOTE
    ws["N2"] = "카드·은행 CSV는 `python -m household_finance import`로 자동 분류·중복제거 후 추가됩니다."
    ws["N2"].font = F_NOTE
    widths(ws, {"A": 11, "B": 9, "C": 26, "D": 12, "E": 12, "F": 9, "G": 6, "H": 8, "I": 10, "J": 14, "K": 16, "L": 9})
    ws.column_dimensions["L"].hidden = True
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:K{max(2, len(txs) + 1)}"


BUDGET_FIRST, BUDGET_LAST = 4, 43
BUDGET_TOTAL_MONTHLY, BUDGET_TOTAL_YEARLY = 45, 46


def build_budget(ws, budgets) -> None:
    title(ws, "📋 예산 대비 실적", "고정비·변동비는 월 예산, 비정기비는 연 예산(경과 월수만큼 안분)과 비교합니다. 실적은 대시보드 '보기' 구성원 기준.")
    write_header(ws, 3, ["카테고리", "대분류", "기준", "예산", "경과 예산", "실적", "집행률", "잔여", "상태",
                         "실적-본인", "실적-배우자", "실적-공동", "(알림용)"], input_sheet=True)
    for c in range(5, 14):
        ws.cell(row=3, column=c).fill = FILL_HEADER
    budget_rows = sorted(((b.category, b.basis, b.amount) for b in budgets if b.category), key=lambda b: b[1] != "월")
    for i in range(BUDGET_LAST - BUDGET_FIRST + 1):
        r = BUDGET_FIRST + i
        if i < len(budget_rows):
            name, basis, amount = budget_rows[i]
            put(ws, f"A{r}", name, font=F_INPUT)
            put(ws, f"C{r}", basis, font=F_INPUT, align=CENTER)
            put(ws, f"D{r}", amount, MONEY, font=F_INPUT)
        else:
            for c in "ACD":
                put(ws, f"{c}{r}", None, MONEY if c == "D" else None, font=F_INPUT)
        put(ws, f"B{r}", f"=IF(A{r}=\"\",\"\",IFERROR(INDEX({q(s.CATEGORIES)}$B$2:$B$200,MATCH(A{r},{q(s.CATEGORIES)}$A$2:$A$200,0)),\"?\"))", align=CENTER)
        put(ws, f"E{r}", f'=IF(A{r}="","",IF(C{r}="연",D{r}*{S("monthno")}/12,D{r}))', MONEY)

        def actual(member_crit: str) -> str:
            yearly = (f'SUMIFS({tx("금액")},{tx("카테고리")},$A{r},{tx("월번호")},">="&{S("yearstart")},'
                      f'{tx("월번호")},"<="&{S("basenum")},{tx("구성원")},{member_crit})')
            monthly = f'SUMIFS({tx("금액")},{tx("카테고리")},$A{r},{tx("월")},{S("base")},{tx("구성원")},{member_crit})'
            return f'=IF($A{r}="","",IF($C{r}="연",{yearly},{monthly}))'

        put(ws, f"F{r}", actual(S("crit")), MONEY)
        put(ws, f"G{r}", f'=IF(OR(A{r}="",N(E{r})=0),"",F{r}/E{r})', PCT)
        put(ws, f"H{r}", f'=IF(A{r}="","",E{r}-F{r})', MONEY)
        put(ws, f"I{r}", f'=IF(OR(A{r}="",N(E{r})=0),"",IF(G{r}>1,"🔴 초과",IF(AND(G{r}>=0.9,B{r}<>"{s.FIXED}"),"⚠ 주의","✅ 양호")))', align=CENTER)
        for col, member in zip("JKL", s.OWNERS):
            put(ws, f"{col}{r}", actual(f'"{member}"'), MONEY)
        put(ws, f"M{r}", f'=IF(ISNUMBER(SEARCH("초과",I{r})),A{r}&" "&TEXT(G{r},"0%"),"")', font=F_NOTE)
    a, b = BUDGET_FIRST, BUDGET_LAST
    for r, label, basis in [(BUDGET_TOTAL_MONTHLY, "월 예산 합계 (고정비+변동비)", "월"), (BUDGET_TOTAL_YEARLY, "연 예산 합계 (비정기비, 경과분)", "연")]:
        put(ws, f"A{r}", label, font=F_BOLD, fill=FILL_TOTAL)
        for col in "DEFJKL":
            put(ws, f"{col}{r}", f'=SUMIFS({col}${a}:{col}${b},$C${a}:$C${b},"{basis}")', MONEY, font=F_BOLD, fill=FILL_TOTAL)
        put(ws, f"G{r}", f"=IF(E{r}=0,0,F{r}/E{r})", PCT, font=F_BOLD, fill=FILL_TOTAL)
        put(ws, f"H{r}", f"=E{r}-F{r}", MONEY, font=F_BOLD, fill=FILL_TOTAL)
        put(ws, f"I{r}", f'=IF(E{r}=0,"",IF(G{r}>1,"🔴 초과",IF(G{r}>=0.9,"⚠ 주의","✅ 양호")))', font=F_BOLD, fill=FILL_TOTAL, align=CENTER)
    status_colors(ws, f"I{BUDGET_FIRST}:I{BUDGET_TOTAL_YEARLY}")
    add_list_validation(ws, f"A{BUDGET_FIRST}:A{BUDGET_LAST}", f"={q(s.CATEGORIES)}$A$2:$A$200")
    add_list_validation(ws, f"C{BUDGET_FIRST}:C{BUDGET_LAST}", '"월,연"')
    widths(ws, {"A": 26, "B": 9, "C": 6, "D": 13, "E": 13, "F": 13, "G": 9, "H": 13, "I": 10,
                "J": 12, "K": 12, "L": 12, "M": 16})
    ws.freeze_panes = "B4"


# ---------------------------------------------------------------- 손익계산서
PNL_MONTH_COLS = [get_column_letter(c) for c in range(2, 14)]   # B..M (M = 기준월)


def build_pnl(ws) -> dict[str, int]:
    title(ws, "📊 손익계산서 (월별)", "최근 12개월. 대시보드 '보기' 구성원 기준으로 집계됩니다. 저축·투자·원금상환은 '자본이동'으로 소비에서 제외.")
    write_header(ws, 3, ["항목"] + [""] * 12 + ["12개월 합계", "월평균", "최근 3개월 평균"])
    for i, col in enumerate(PNL_MONTH_COLS):
        ws[f"{col}3"] = f"={month_offset(i - 11)}"
    rows: dict[str, int] = {}
    kinds: dict[int, str] = {}   # 행 → 'amount' | 'ratio'
    formulas: dict[int, callable] = {}
    r = 4

    def cat_row(name: str) -> None:
        nonlocal r
        rows[f"cat:{name}"] = r
        formulas[r] = lambda c, name=name: f'SUMIFS({tx("금액")},{tx("월")},{c}$3,{tx("카테고리")},"{name}",{tx("구성원")},{S("crit")})'
        kinds[r] = "amount"
        ws[f"A{r}"] = "   " + name
        r += 1

    def group_total(label: str, group: str) -> None:
        nonlocal r
        rows[label] = r
        formulas[r] = lambda c, group=group: f'SUMIFS({tx("금액")},{tx("월")},{c}$3,{tx("대분류")},"{group}",{tx("구성원")},{S("crit")})'
        kinds[r] = "amount"
        ws[f"A{r}"] = label
        r += 1

    def derived(label: str, fn, kind: str = "amount") -> None:
        nonlocal r
        rows[label] = r
        formulas[r] = fn
        kinds[r] = kind
        ws[f"A{r}"] = label
        r += 1

    def header_row(label: str) -> None:
        nonlocal r
        section(ws, r, label, 1, 16)
        r += 1

    for group, total_label in [(s.INCOME, "소득 합계"), (s.FIXED, "고정비 합계"), (s.VARIABLE, "변동비 합계"), (s.IRREGULAR, "비정기비 합계")]:
        header_row(f"[{group}]")
        for name, g, *_ in s.CATEGORY_TABLE:
            if g == group:
                cat_row(name)
        group_total(total_label, group)
    r += 1
    derived("소비지출 합계", lambda c: f'{c}{rows["고정비 합계"]}+{c}{rows["변동비 합계"]}+{c}{rows["비정기비 합계"]}')
    derived("잉여 (소득-소비지출)", lambda c: f'{c}{rows["소득 합계"]}-{c}{rows["소비지출 합계"]}')
    derived("저축률", lambda c: f'IF({c}{rows["소득 합계"]}=0,0,{c}{rows["잉여 (소득-소비지출)"]}/{c}{rows["소득 합계"]})', "ratio")
    r += 1
    header_row(f"[{s.CAPITAL}]")
    for name, g, *_ in s.CATEGORY_TABLE:
        if g == s.CAPITAL:
            cat_row(name)
    group_total("자본이동 합계", s.CAPITAL)
    derived("투자 납입액 (투자+연금)", lambda c: "+".join(f'{c}{rows["cat:" + n]}' for n in s.INVEST_CATEGORIES))
    derived("순현금흐름 (잉여-자본이동)", lambda c: f'{c}{rows["잉여 (소득-소비지출)"]}-{c}{rows["자본이동 합계"]}')
    r += 1
    header_row("[관리 지표]")
    derived("필수지출", lambda c: f'SUMIFS({tx("금액")},{tx("월")},{c}$3,{tx("필수")},"Y",{tx("구성원")},{S("crit")})')
    derived("고정비 비율", lambda c: f'IF({c}{rows["소득 합계"]}=0,0,{c}{rows["고정비 합계"]}/{c}{rows["소득 합계"]})', "ratio")
    derived("투자 납입률", lambda c: f'IF({c}{rows["소득 합계"]}=0,0,{c}{rows["투자 납입액 (투자+연금)"]}/{c}{rows["소득 합계"]})', "ratio")
    derived("미분류 금액", lambda c: f'SUMIFS({tx("금액")},{tx("월")},{c}$3,{tx("대분류")},"{s.UNCATEGORIZED}",{tx("구성원")},{S("crit")})')

    bold_labels = {"소득 합계", "고정비 합계", "변동비 합계", "비정기비 합계", "소비지출 합계", "잉여 (소득-소비지출)",
                   "저축률", "자본이동 합계", "투자 납입액 (투자+연금)", "순현금흐름 (잉여-자본이동)"}
    for row, fn in formulas.items():
        label = ws[f"A{row}"].value.strip()
        is_bold = label in bold_labels
        fmt = PCT if kinds[row] == "ratio" else MONEY
        font = F_BOLD if is_bold else F_BASE
        fill = FILL_TOTAL if is_bold else None
        ws[f"A{row}"].font = font
        ws[f"A{row}"].border = BOX
        if fill:
            ws[f"A{row}"].fill = fill
        for c in PNL_MONTH_COLS:
            put(ws, f"{c}{row}", "=" + fn(c), fmt, font=font, fill=fill)
        if kinds[row] == "amount" and not label.startswith(("소비지출", "잉여", "투자 납입액", "순현금")):
            put(ws, f"N{row}", f"=SUM(B{row}:M{row})", fmt, font=font, fill=fill)
            put(ws, f"O{row}", f"=N{row}/12", fmt, font=font, fill=fill)
            put(ws, f"P{row}", f"=AVERAGE(K{row}:M{row})", fmt, font=font, fill=fill)
        else:   # 파생 항목은 같은 공식을 합계·평균 열에 그대로 적용 (비율을 평균내지 않는다)
            for c in "NOP":
                put(ws, f"{c}{row}", "=" + fn(c), fmt, font=font, fill=fill)
    widths(ws, {"A": 28, **{c: 11.5 for c in PNL_MONTH_COLS}, "N": 13, "O": 12, "P": 13})
    ws.freeze_panes = "B4"
    return rows


# ---------------------------------------------------------------- 재무상태표
BS = {"assets_first": 4, "total_assets": 9, "liabilities": 10, "net": 11, "available_net": 12, "invest": 13,
      "debt_ratio": 14, "emergency": 15, "cash_available": 16, "liq_first": 19,
      "member_first": 24, "member_total": 27, "trend_first": 31, "trend_last": 42, "acct_first": 46}


def build_balance(ws) -> None:
    title(ws, "🏦 재무상태표", "스냅샷(월말 잔액) 기준. 대시보드 '보기' 구성원 기준으로 집계됩니다.")
    write_header(ws, 3, ["구분", "", "", "증감", "증감률", "총자산 대비"])
    ws["B3"] = f"={S('base')}"
    ws["C3"] = f"={S('prev')}"

    def by_type(col: str, typ: str) -> str:
        return f'SUMIFS({snap("금액")},{snap("월")},{col}$3,{snap("유형")},"{typ}",{snap("소유자")},{S("crit")})'

    lines = []
    for i, typ in enumerate(s.ASSET_TYPES):
        lines.append((BS["assets_first"] + i, "   " + typ, lambda c, t=typ: by_type(c, t), MONEY, False))
    lines += [
        (BS["total_assets"], "자산 총계", lambda c: f"SUM({c}{BS['assets_first']}:{c}{BS['assets_first'] + 4})", MONEY, True),
        (BS["liabilities"], "부채 총계", lambda c: by_type(c, s.LIABILITY), MONEY, True),
        (BS["net"], "순자산 (자산-부채)", lambda c: f"{c}{BS['total_assets']}-{c}{BS['liabilities']}", MONEY, True),
        (BS["available_net"], "가용 순자산 (부동산 제외)", lambda c: f"{c}{BS['net']}-{c}{BS['assets_first'] + 3}", MONEY, False),
        (BS["invest"], "투자+연금 자산", lambda c: f"{c}{BS['assets_first'] + 1}+{c}{BS['assets_first'] + 2}", MONEY, True),
        (BS["debt_ratio"], "부채비율 (부채/자산)", lambda c: f"IF({c}{BS['total_assets']}=0,0,{c}{BS['liabilities']}/{c}{BS['total_assets']})", PCT, False),
        (BS["emergency"], "비상자금 (즉시 인출 가능 현금성)",
         lambda c: f'SUMIFS({snap("금액")},{snap("월")},{c}$3,{snap("유형")},"현금성",{snap("유동성")},"즉시",{snap("소유자")},{S("crit")})', MONEY, False),
        (BS["cash_available"], "즉시 가용현금 (비상자금-즉시 부채)",
         lambda c: f'{c}{BS["emergency"]}-SUMIFS({snap("금액")},{snap("월")},{c}$3,{snap("유형")},"부채",{snap("유동성")},"즉시",{snap("소유자")},{S("crit")})', MONEY, False),
    ]
    for row, label, fn, fmt, bold in lines:
        font, fill = (F_BOLD, FILL_TOTAL) if bold else (F_BASE, None)
        put(ws, f"A{row}", label, font=font, fill=fill)
        put(ws, f"B{row}", "=" + fn("B"), fmt, font=font, fill=fill)
        put(ws, f"C{row}", "=" + fn("C"), fmt, font=font, fill=fill)
        put(ws, f"D{row}", f"=B{row}-C{row}", PCT if fmt == PCT else MONEY, font=font, fill=fill)
        put(ws, f"E{row}", "" if fmt == PCT else f"=IF(C{row}=0,0,D{row}/ABS(C{row}))", PCT, font=font, fill=fill)
        put(ws, f"F{row}", "" if fmt == PCT else f"=IF($B${BS['total_assets']}=0,0,B{row}/$B${BS['total_assets']})", PCT, font=font, fill=fill)

    section(ws, 18, "유동성별 자산 (기준월)", 1, 6)
    for i, liq in enumerate(s.LIQUIDITY):
        r = BS["liq_first"] + i
        put(ws, f"A{r}", "   " + liq)
        put(ws, f"B{r}", f'=SUMIFS({snap("금액")},{snap("월")},$B$3,{snap("유동성")},"{liq}",{snap("유형")},"<>부채",{snap("소유자")},{S("crit")})', MONEY)
        put(ws, f"F{r}", f"=IF($B${BS['total_assets']}=0,0,B{r}/$B${BS['total_assets']})", PCT)

    section(ws, BS["member_first"] - 2, "구성원별 현황 (기준월 · 보기 선택과 무관)", 1, 6)
    write_header(ws, BS["member_first"] - 1, ["구성원", "자산", "부채", "순자산", "투자+연금", "현금성"])
    for i, member in enumerate(s.OWNERS):
        r = BS["member_first"] + i
        base = f'{snap("월")},{S("base")},{snap("소유자")},"{member}"'
        put(ws, f"A{r}", member)
        put(ws, f"B{r}", f'=SUMIFS({snap("금액")},{base},{snap("유형")},"<>부채")', MONEY)
        put(ws, f"C{r}", f'=SUMIFS({snap("금액")},{base},{snap("유형")},"부채")', MONEY)
        put(ws, f"D{r}", f"=B{r}-C{r}", MONEY)
        put(ws, f"E{r}", f'=SUMIFS({snap("금액")},{base},{snap("유형")},"투자")+SUMIFS({snap("금액")},{base},{snap("유형")},"연금")', MONEY)
        put(ws, f"F{r}", f'=SUMIFS({snap("금액")},{base},{snap("유형")},"현금성")', MONEY)
    r = BS["member_total"]
    put(ws, f"A{r}", "합계", font=F_BOLD, fill=FILL_TOTAL)
    for col in "BCDEF":
        put(ws, f"{col}{r}", f"=SUM({col}{BS['member_first']}:{col}{r - 1})", MONEY, font=F_BOLD, fill=FILL_TOTAL)

    write_header(ws, 30, ["월", "총자산", "총부채", "순자산", "투자+연금", "현금성"])
    section(ws, 29, "순자산 추이 (최근 12개월 · 보기 기준)", 1, 6)
    for i in range(12):
        r = BS["trend_first"] + i
        put(ws, f"A{r}", f"={month_offset(i - 11)}", align=CENTER)
        crit = f'{snap("월")},$A{r},{snap("소유자")},{S("crit")}'
        put(ws, f"B{r}", f'=SUMIFS({snap("금액")},{crit},{snap("유형")},"<>부채")', MONEY)
        put(ws, f"C{r}", f'=SUMIFS({snap("금액")},{crit},{snap("유형")},"부채")', MONEY)
        put(ws, f"D{r}", f"=B{r}-C{r}", MONEY)
        put(ws, f"E{r}", f'=SUMIFS({snap("금액")},{crit},{snap("유형")},"투자")+SUMIFS({snap("금액")},{crit},{snap("유형")},"연금")', MONEY)
        put(ws, f"F{r}", f'=SUMIFS({snap("금액")},{crit},{snap("유형")},"현금성")', MONEY)

    section(ws, 44, "계좌별 잔액 (기준월 · 전체)", 1, 7)
    write_header(ws, 45, ["계좌ID", "계좌명", "유형", "소유자", "기준월", "전월", "증감"])
    for i in range(s.ACCOUNT_ROWS):
        r, src = BS["acct_first"] + i, i + 2
        for col, scol in zip("ABCD", "ABDE"):
            put(ws, f"{col}{r}", f'=IF({q(s.ACCOUNTS)}$A{src}="","",{q(s.ACCOUNTS)}{scol}{src})')
        put(ws, f"E{r}", f'=IF(A{r}="","",SUMIFS({snap("금액")},{snap("월")},{S("base")},{snap("계좌ID")},A{r}))', MONEY)
        put(ws, f"F{r}", f'=IF(A{r}="","",SUMIFS({snap("금액")},{snap("월")},{S("prev")},{snap("계좌ID")},A{r}))', MONEY)
        put(ws, f"G{r}", f'=IF(A{r}="","",E{r}-F{r})', MONEY)
    widths(ws, {"A": 32, "B": 18, "C": 18, "D": 16, "E": 16, "F": 14, "G": 14})
    ws.freeze_panes = "B4"


# ---------------------------------------------------------------- 투자
INV = {"alloc_first": 4, "alloc_total": 9, "contrib": 12, "tax_first": 20, "hold_header": 25, "hold_total": 26, "hold_first": 27}


def build_invest(ws, holdings: list[tuple], pnl: dict[str, int], allocation: dict[str, float]) -> None:
    title(ws, "📈 투자 포트폴리오", "보유종목 표에 수량·현재가를 입력하면 자산배분·수익률이 계산됩니다. 구글 시트에서는 현재가에 =GOOGLEFINANCE(시세코드) 사용 가능.")
    write_header(ws, 3, ["자산군", "목표 비중", "평가금액", "현재 비중", "괴리(%p)", "상태", "목표까지 조정금액", "(알림용)"])
    ws["B3"].fill = FILL_INPUT_HEADER
    hf, hl = INV["hold_first"], INV["hold_first"] + s.HOLDING_ROWS - 1
    for i, klass in enumerate(s.ASSET_CLASSES):
        r = INV["alloc_first"] + i
        put(ws, f"A{r}", klass)
        put(ws, f"B{r}", allocation.get(klass, 0.0), PCT, font=F_INPUT, fill=FILL_KEY)
        put(ws, f"C{r}", f"=SUMIFS($K${hf}:$K${hl},$F${hf}:$F${hl},A{r},$C${hf}:$C${hl},{S('crit')})", MONEY)
        put(ws, f"D{r}", f"=IF($C${INV['alloc_total']}=0,0,C{r}/$C${INV['alloc_total']})", PCT)
        put(ws, f"E{r}", f"=D{r}-B{r}", PCT)
        put(ws, f"F{r}", f'=IF($C${INV["alloc_total"]}=0,"",IF(ABS(E{r})>{S("band")},"⚠ 리밸런싱","✅ 적정"))', align=CENTER)
        put(ws, f"G{r}", f"=B{r}*$C${INV['alloc_total']}-C{r}", MONEY)
        put(ws, f"H{r}", f'=IF(ISNUMBER(SEARCH("리밸런싱",F{r})),A{r}&" "&TEXT(E{r},"+0%;-0%"),"")', font=F_NOTE)
    r = INV["alloc_total"]
    put(ws, f"A{r}", "합계", font=F_BOLD, fill=FILL_TOTAL)
    for col, fmt in [("B", PCT), ("C", MONEY), ("D", PCT)]:
        put(ws, f"{col}{r}", f"=SUM({col}{INV['alloc_first']}:{col}{r - 1})", fmt, font=F_BOLD, fill=FILL_TOTAL)
    put(ws, f"E{r}", '=IF(ROUND(B9,4)<>1,"⚠ 목표 비중 합이 100%가 아님","")', font=F_NOTE)
    status_colors(ws, f"F{INV['alloc_first']}:F{INV['alloc_total'] - 1}")
    ws["I3"] = "리밸런싱 알림은 가계 전체 포트폴리오 기준(대시보드 보기 '전체')에서만 표시됩니다."
    ws["I3"].font = F_NOTE

    section(ws, 11, "투자금 확대 트래킹", 1, 6)
    inv_row = pnl["투자 납입액 (투자+연금)"]
    lines = [
        ("이번 달 투자 납입액", f"={q(s.PNL)}M{inv_row}", f"={S('t_invest_view')}", "=IF(C{r}=0,0,B{r}/C{r})"),
        ("최근 12개월 누적 납입", f"={q(s.PNL)}N{inv_row}", f"={S('t_invest_view')}*12", "=IF(C{r}=0,0,B{r}/C{r})"),
        ("월평균 납입 (12개월)", f"={q(s.PNL)}O{inv_row}", f"={S('t_invest_view')}", "=IF(C{r}=0,0,B{r}/C{r})"),
        ("투자+연금 자산 (기준월)", f"={q(s.BALANCE)}B{BS['invest']}", f"={q(s.BALANCE)}C{BS['invest']}", "=IF(C{r}=0,0,B{r}/C{r}-1)"),
        ("자산 증가 중 운용수익 (추정)", f"={q(s.BALANCE)}D{BS['invest']}-B{INV['contrib']}", "", ""),
    ]
    put(ws, "B11", "실적", font=F_HEADER, fill=FILL_HEADER, align=CENTER)
    put(ws, "C11", "목표/전월", font=F_HEADER, fill=FILL_HEADER, align=CENTER)
    put(ws, "D11", "달성률/증가율", font=F_HEADER, fill=FILL_HEADER, align=CENTER)
    for i, (label, actual, target, ratio) in enumerate(lines):
        r = INV["contrib"] + i
        put(ws, f"A{r}", label)
        put(ws, f"B{r}", actual, MONEY)
        put(ws, f"C{r}", target, MONEY)
        put(ws, f"D{r}", ratio.format(r=r), PCT)
    ws[f"E{INV['contrib'] + 4}"] = "증감 − 이번 달 납입. 퇴직연금 회사 적립분 등이 섞일 수 있어 추정치입니다."
    ws[f"E{INV['contrib'] + 4}"].font = F_NOTE

    section(ws, 18, "절세 계좌 납입 현황 (올해 1월~기준월, 거래내역 '내용' 키워드로 집계)", 1, 6)
    write_header(ws, 19, ["항목", "연간 한도", "올해 납입", "잔여 한도", "소진율", "내용 키워드"])
    ws["F19"].fill = FILL_INPUT_HEADER

    def ytd(kw_cell: str) -> str:
        return (f'SUMIFS({tx("금액")},{tx("월번호")},">="&{S("yearstart")},{tx("월번호")},"<="&{S("basenum")},'
                f'{tx("내용")},{kw_cell},{tx("구성원")},{S("crit")})')
    tf = INV["tax_first"]
    tax = [
        ("연금저축", f"={S('lim_pension')}", f"={ytd(f'F{tf}')}", "*연금저축*"),
        ("연금저축+IRP 합산", f"={S('lim_pension_total')}", f"=C{tf}+{ytd(f'F{tf + 1}')}", "*IRP*"),
        ("ISA", f"={S('lim_isa')}", f"={ytd(f'F{tf + 2}')}", "*ISA*"),
    ]
    for i, (label, limit, paid, kw) in enumerate(tax):
        r = tf + i
        put(ws, f"A{r}", label)
        put(ws, f"B{r}", limit, MONEY)
        put(ws, f"C{r}", paid, MONEY)
        put(ws, f"D{r}", f"=MAX(0,B{r}-C{r})", MONEY)
        put(ws, f"E{r}", f"=IF(B{r}=0,0,C{r}/B{r})", PCT)
        put(ws, f"F{r}", kw, font=F_INPUT)
    ws[f"A{tf + 3}"] = "'연금저축+IRP 합산'의 키워드 칸은 IRP 납입을 찾는 키워드입니다 (연금저축분은 위 행 값을 더함)."
    ws[f"A{tf + 3}"].font = F_NOTE

    headers = ["계좌ID", "계좌명", "소유자", "종목명", "시세코드", "자산군", "수량", "평균단가", "현재가", "매입금액", "평가금액", "평가손익", "수익률"]
    write_header(ws, INV["hold_header"], headers, input_sheet=True)
    for c in (2, 3, 10, 11, 12, 13):
        ws.cell(row=INV["hold_header"], column=c).fill = FILL_HEADER
    section(ws, INV["hold_header"] - 1, "보유 종목 (파란 글씨 열 입력)", 1, 13)
    t = INV["hold_total"]
    put(ws, f"A{t}", "보유종목 합계 (보기 기준)", font=F_BOLD, fill=FILL_TOTAL)
    for col in "JKL":
        put(ws, f"{col}{t}", f"=SUMIFS({col}{hf}:{col}{hl},$C${hf}:$C${hl},{S('crit')})", MONEY, font=F_BOLD, fill=FILL_TOTAL)
    put(ws, f"M{t}", f"=IF(J{t}=0,0,L{t}/J{t})", PCT, font=F_BOLD, fill=FILL_TOTAL)
    acct = f"{q(s.ACCOUNTS)}$A$2:$A${s.ACCOUNT_ROWS + 1}"
    for i in range(s.HOLDING_ROWS):
        r = hf + i
        h = holdings[i] if i < len(holdings) else None
        values = dict(zip(["A", "D", "E", "F", "G", "H", "I"], h)) if h else {}
        for col in "ADEFGHI":
            put(ws, f"{col}{r}", values.get(col), MONEY if col in "GHI" else None, font=F_INPUT)
        put(ws, f"B{r}", f'=IF(A{r}="","",IFERROR(INDEX({q(s.ACCOUNTS)}$B$2:$B${s.ACCOUNT_ROWS + 1},MATCH(A{r},{acct},0)),"?"))')
        put(ws, f"C{r}", f'=IF(A{r}="","",IFERROR(INDEX({q(s.ACCOUNTS)}$E$2:$E${s.ACCOUNT_ROWS + 1},MATCH(A{r},{acct},0)),"?"))')
        put(ws, f"J{r}", f'=IF(A{r}="","",G{r}*H{r})', MONEY)
        put(ws, f"K{r}", f'=IF(A{r}="","",G{r}*I{r})', MONEY)
        put(ws, f"L{r}", f'=IF(A{r}="","",K{r}-J{r})', MONEY)
        put(ws, f"M{r}", f'=IF(OR(A{r}="",N(J{r})=0),"",L{r}/J{r})', PCT)
    add_list_validation(ws, f"A{hf}:A{hl}", f"={acct}")
    add_list_validation(ws, f"F{hf}:F{hl}", f"={q(s.SETTINGS)}$I$3:$I$7")
    widths(ws, {"A": 26, "B": 18, "C": 13, "D": 22, "E": 14, "F": 10, "G": 10, "H": 12, "I": 12, "J": 14, "K": 14, "L": 13, "M": 9})
    ws.freeze_panes = "A4"


# ---------------------------------------------------------------- 부채
DEBT_FIRST, DEBT_SUM = 4, 16


def build_debt(ws, debts: list[tuple], pnl: dict[str, int]) -> None:
    title(ws, "💳 부채 관리", "잔액은 스냅샷 기준월 값을 자동으로 가져옵니다. 상환 우선순위는 금리가 높은 순.")
    headers = ["대출명", "계좌ID", "소유자", "잔액(기준월)", "금리(연)", "만기일", "상환방식", "월 원리금", "월 이자(추정)",
               "연간 원리금", "금리 +1%p 시 월 증가", "남은 개월", "상환 우선순위"]
    write_header(ws, 3, headers, input_sheet=True)
    for c in (3, 4, 9, 10, 11, 12, 13):
        ws.cell(row=3, column=c).fill = FILL_HEADER
    last = DEBT_FIRST + s.DEBT_ROWS - 1
    acct = f"{q(s.ACCOUNTS)}$A$2:$A${s.ACCOUNT_ROWS + 1}"
    for i in range(s.DEBT_ROWS):
        r = DEBT_FIRST + i
        d = debts[i] if i < len(debts) else (None,) * 6
        name, acc, rate, maturity, method, payment = d
        put(ws, f"A{r}", name, font=F_INPUT)
        put(ws, f"B{r}", acc, font=F_INPUT)
        put(ws, f"E{r}", rate, "0.00%", font=F_INPUT)
        put(ws, f"F{r}", maturity, DATE_FMT, font=F_INPUT)
        put(ws, f"G{r}", method, font=F_INPUT)
        put(ws, f"H{r}", payment, MONEY, font=F_INPUT)
        put(ws, f"C{r}", f'=IF(B{r}="","",IFERROR(INDEX({q(s.ACCOUNTS)}$E$2:$E${s.ACCOUNT_ROWS + 1},MATCH(B{r},{acct},0)),"?"))')
        put(ws, f"D{r}", f'=IF(B{r}="","",SUMIFS({snap("금액")},{snap("월")},{S("base")},{snap("계좌ID")},B{r}))', MONEY)
        put(ws, f"I{r}", f'=IF(B{r}="","",D{r}*E{r}/12)', MONEY)
        put(ws, f"J{r}", f'=IF(B{r}="","",H{r}*12)', MONEY)
        put(ws, f"K{r}", f'=IF(B{r}="","",D{r}*0.01/12)', MONEY)
        put(ws, f"L{r}", f'=IF(F{r}="","",MAX(0,ROUND((F{r}-{S("today")})/30.4,0)))', '0"개월"')
        put(ws, f"M{r}", f'=IF(OR(B{r}="",E{r}=""),"",RANK(E{r},$E${DEBT_FIRST}:$E${last}))', '0"순위"')
    add_list_validation(ws, f"B{DEBT_FIRST}:B{last}", f"={acct}")
    rng = lambda col: f"{col}{DEBT_FIRST}:{col}{last}"
    summary = [
        ("총 대출잔액 (보기 기준)", f"=SUMIFS({rng('D')},{rng('C')},{S('crit')})", MONEY),
        ("월 원리금 합계", f"=SUMIFS({rng('H')},{rng('C')},{S('crit')})", MONEY),
        ("연간 원리금", f"=B{DEBT_SUM + 1}*12", MONEY),
        ("연소득 (최근 12개월 · 공동 보기는 가계 전체)",
         f'=IF({S("view")}="공동",SUMIFS({tx("금액")},{tx("대분류")},"{s.INCOME}",{tx("월번호")},">="&VALUE(SUBSTITUTE({month_offset(-11)},"-","")),{tx("월번호")},"<="&{S("basenum")}),{q(s.PNL)}N{pnl["소득 합계"]})', MONEY),
        ("DSR (연간 원리금/연소득)", f"=IF(B{DEBT_SUM + 3}=0,0,B{DEBT_SUM + 2}/B{DEBT_SUM + 3})", PCT),
        ("DSR 상한 (설정)", f"={S('t_dsr')}", PCT),
        ("금리 1%p 상승 시 월 부담 증가", f"=SUMIFS({rng('K')},{rng('C')},{S('crit')})", MONEY),
        ("가중평균 금리", f"=IF(SUM({rng('D')})=0,0,SUMPRODUCT({rng('D')},{rng('E')})/SUM({rng('D')}))", "0.00%"),
    ]
    section(ws, DEBT_SUM - 1, "요약", 1, 3)
    for i, (label, formula, fmt) in enumerate(summary):
        r = DEBT_SUM + i
        put(ws, f"A{r}", label, font=F_BOLD if "DSR (" in label else F_BASE)
        put(ws, f"B{r}", formula, fmt, font=F_BOLD if "DSR (" in label else F_BASE)
    put(ws, f"C{DEBT_SUM + 4}", f'=IF(B{DEBT_SUM + 4}>B{DEBT_SUM + 5},"⚠ 상한 초과","✅ 양호")', align=CENTER)
    status_colors(ws, f"C{DEBT_SUM + 4}")
    widths(ws, {"A": 30, "B": 16, "C": 12, "D": 15, "E": 9, "F": 11, "G": 11, "H": 12, "I": 12, "J": 13, "K": 15, "L": 9, "M": 11})
    ws.freeze_panes = "A4"


DEBT_DSR = DEBT_SUM + 4

# ---------------------------------------------------------------- 목표
GOAL_FIRST, GOAL_SUM = 4, 16


def build_goals(ws, goals: list[tuple], pnl: dict[str, int]) -> None:
    title(ws, "🎯 재무 목표 (중장기 사업계획)", "연결계좌의 기준월 잔액 합으로 진척률을 계산합니다. 계획 진척률 = 시작일~목표일 중 오늘까지 경과 비율.")
    headers = ["목표명", "담당", "목표금액", "시작일", "목표일", "연결계좌1", "연결계좌2", "연결계좌3", "현재금액", "진척률",
               "계획 진척률", "상태", "남은 개월", "필요 월적립액", "(진척 반영액)", "(알림용)"]
    write_header(ws, 3, headers, input_sheet=True)
    for c in range(9, 17):
        ws.cell(row=3, column=c).fill = FILL_HEADER
    last = GOAL_FIRST + s.GOAL_ROWS - 1
    acct = f"{q(s.ACCOUNTS)}$A$2:$A${s.ACCOUNT_ROWS + 1}"
    for i in range(s.GOAL_ROWS):
        r = GOAL_FIRST + i
        g = goals[i] if i < len(goals) else (None,) * 8
        name, owner, amount, start, end, a1, a2, a3 = g
        put(ws, f"A{r}", name, font=F_INPUT)
        put(ws, f"B{r}", owner, font=F_INPUT, align=CENTER)
        if name and amount is None:   # 비상자금: 목표 개월수 × 최근 3개월 평균 필수지출
            put(ws, f"C{r}", f"=ROUND({S('t_emergency')}*{q(s.PNL)}P{pnl['필수지출']},-4)", MONEY)
            ws[f"C{r}"].comment = Comment("수식: 설정의 비상자금 목표 개월수 × 최근 3개월 평균 필수지출", "dashboard")
        else:
            put(ws, f"C{r}", amount, MONEY, font=F_INPUT)
        put(ws, f"D{r}", start, DATE_FMT, font=F_INPUT)
        put(ws, f"E{r}", end, DATE_FMT, font=F_INPUT)
        for col, v in zip("FGH", (a1, a2, a3)):
            put(ws, f"{col}{r}", v or None, font=F_INPUT, align=CENTER)
        parts = "+".join(f'IF({col}{r}="",0,SUMIFS({snap("금액")},{snap("월")},{S("base")},{snap("계좌ID")},{col}{r}))' for col in "FGH")
        put(ws, f"I{r}", f'=IF(A{r}="","",{parts})', MONEY)
        put(ws, f"J{r}", f'=IF(OR(A{r}="",N(C{r})=0),"",MIN(1,I{r}/C{r}))', PCT)
        put(ws, f"K{r}", f'=IF(OR(A{r}="",D{r}="",E{r}=""),"",IF(E{r}<=D{r},1,MAX(0,MIN(1,({S("today")}-D{r})/(E{r}-D{r})))))', PCT)
        put(ws, f"L{r}", f'=IF(OR(A{r}="",J{r}=""),"",IF(J{r}>=1,"🎉 달성",IF(J{r}>=K{r}-{S("goal_tol")},"✅ 순항","⚠ 지연")))', align=CENTER)
        put(ws, f"M{r}", f'=IF(OR(A{r}="",E{r}=""),"",MAX(1,ROUND((E{r}-{S("today")})/30.4,0)))', '0"개월"')
        put(ws, f"N{r}", f'=IF(OR(A{r}="",M{r}=""),"",MAX(0,(C{r}-I{r})/M{r}))', MONEY)
        put(ws, f"O{r}", f'=IF(A{r}="",0,MIN(N(I{r}),N(C{r})))', MONEY)
        put(ws, f"P{r}", f'=IF(ISNUMBER(SEARCH("지연",L{r})),A{r}&" "&TEXT(J{r},"0%"),"")', font=F_NOTE)
    status_colors(ws, f"L{GOAL_FIRST}:L{last}")
    add_list_validation(ws, f"B{GOAL_FIRST}:B{last}", f"={q(s.SETTINGS)}$E$3:$E$6")
    add_list_validation(ws, f"F{GOAL_FIRST}:H{last}", f"={acct}")
    put(ws, f"A{GOAL_SUM}", "전체 목표 가중 달성률", font=F_BOLD)
    put(ws, f"B{GOAL_SUM}", f"=IF(SUM(C{GOAL_FIRST}:C{last})=0,0,SUM(O{GOAL_FIRST}:O{last})/SUM(C{GOAL_FIRST}:C{last}))", PCT, font=F_BOLD)
    put(ws, f"A{GOAL_SUM + 1}", "노후 준비율 ('노후'로 시작하는 목표)")
    put(ws, f"B{GOAL_SUM + 1}", f'=IFERROR(INDEX(J{GOAL_FIRST}:J{last},MATCH("노후*",A{GOAL_FIRST}:A{last},0)),0)', PCT)
    put(ws, f"A{GOAL_SUM + 2}", "지연 목표 수")
    put(ws, f"B{GOAL_SUM + 2}", f'=COUNTIF(L{GOAL_FIRST}:L{last},"*지연*")', '0"건"')
    put(ws, f"A{GOAL_SUM + 3}", "목표 달성에 필요한 월 적립 합계")
    put(ws, f"B{GOAL_SUM + 3}", f"=SUM(N{GOAL_FIRST}:N{last})", MONEY)
    ws[f"C{GOAL_SUM + 1}"] = "국민연금 예상수령액은 포함되지 않습니다 - 목표금액에서 차감해 입력하세요."
    ws[f"C{GOAL_SUM + 1}"].font = F_NOTE
    widths(ws, {"A": 34, "B": 14, "C": 14, "D": 11, "E": 11, "F": 9, "G": 9, "H": 9, "I": 14, "J": 9, "K": 10, "L": 10,
                "M": 9, "N": 14, "O": 13, "P": 22})
    ws.freeze_panes = "B4"


# ---------------------------------------------------------------- 보험
INS_FIRST, INS_MATRIX = 4, 17


def build_insurance(ws, policies: list[tuple], pnl: dict[str, int]) -> None:
    title(ws, "🛡 보험·리스크 관리", "보장금액을 입력하면 구성원별 보장 공백을 자동으로 찾아냅니다 (0 또는 빈칸 = 보장 없음).")
    headers = ["피보험자", "보험사", "상품명"] + s.COVERAGES + ["월보험료", "만기일", "갱신형(Y/N)"]
    write_header(ws, 3, headers, input_sheet=True)
    last = INS_FIRST + s.INSURANCE_ROWS - 1
    for i in range(s.INSURANCE_ROWS):
        r = INS_FIRST + i
        p = policies[i] if i < len(policies) else (None,) * 11
        for c, v in enumerate(p, start=1):
            fmt = MONEY if 4 <= c <= 9 else DATE_FMT if c == 10 else None
            put(ws, f"{get_column_letter(c)}{r}", v if v != 0 else None, fmt, font=F_INPUT)
    add_list_validation(ws, f"A{INS_FIRST}:A{last}", f"={q(s.SETTINGS)}$E$3:$E$6")

    section(ws, INS_MATRIX - 2, "구성원별 보장 현황", 1, 7)
    write_header(ws, INS_MATRIX - 1, ["구성원"] + s.COVERAGES + ["월보험료"])
    members = ["본인", "배우자", "자녀"]
    for i, member in enumerate(members):
        r = INS_MATRIX + i
        put(ws, f"A{r}", member, font=F_BOLD)
        for j, cov in enumerate(s.COVERAGES):
            src = get_column_letter(4 + j)
            col = get_column_letter(2 + j)
            amount = f"SUMIFS(${src}${INS_FIRST}:${src}${last},$A${INS_FIRST}:$A${last},$A{r})"
            if member == "자녀" and cov == "사망":
                put(ws, f"{col}{r}", "-", align=CENTER)
            else:
                put(ws, f"{col}{r}", f'=IF({amount}>0,"✅ "&TEXT({amount}/10000,"#,##0")&"만","❌ 공백")', align=CENTER)
        put(ws, f"G{r}", f"=SUMIFS($I${INS_FIRST}:$I${last},$A${INS_FIRST}:$A${last},$A{r})", MONEY)
    status_colors(ws, f"B{INS_MATRIX}:F{INS_MATRIX + 2}")
    r = INS_MATRIX + 4
    rows = [
        ("월 보험료 합계", f"=SUM(I{INS_FIRST}:I{last})", MONEY),
        ("월평균 소득 (12개월)", f"={q(s.PNL)}O{pnl['소득 합계']}", MONEY),
        ("보험료 부담률 (권장 10% 이하)", f"=IF(B{r + 1}=0,0,B{r}/B{r + 1})", PCT),
        ("보장 공백 수", f'=COUNTIF(B{INS_MATRIX}:F{INS_MATRIX + 2},"*공백*")', '0"건"'),
    ]
    for i, (label, formula, fmt) in enumerate(rows):
        put(ws, f"A{r + i}", label)
        put(ws, f"B{r + i}", formula, fmt)
    widths(ws, {"A": 30, "B": 14, "C": 16, "D": 13, "E": 13, "F": 13, "G": 13, "H": 13, "I": 12, "J": 11, "K": 11})
    ws.freeze_panes = "A4"


INS_GAPS = INS_MATRIX + 7

# ---------------------------------------------------------------- 일정
EVENT_FIRST = 4


def build_events(ws, events: list[tuple]) -> None:
    title(ws, "🗓 일정 (현금흐름 이벤트 캘린더)", "만기·세금·명절·보너스 등. 유입/유출 금액은 현금흐름 예측에 반영되고, 알림 일수 이내 일정은 대시보드에 표시됩니다.")
    write_header(ws, 3, ["일자", "내용", "구분", "금액", "구성원", "월", "D-day", "알림"], input_sheet=True)
    for c in (6, 7, 8):
        ws.cell(row=3, column=c).fill = FILL_HEADER
    last = EVENT_FIRST + s.EVENT_ROWS - 1
    for i in range(s.EVENT_ROWS):
        r = EVENT_FIRST + i
        e = events[i] if i < len(events) else (None,) * 5
        put(ws, f"A{r}", e[0], DATE_FMT, font=F_INPUT)
        put(ws, f"B{r}", e[1], font=F_INPUT)
        put(ws, f"C{r}", e[2], font=F_INPUT, align=CENTER)
        put(ws, f"D{r}", e[3] or None, MONEY, font=F_INPUT)
        put(ws, f"E{r}", e[4], font=F_INPUT, align=CENTER)
        put(ws, f"F{r}", f'=IF(A{r}="","",TEXT(A{r},"yyyy-mm"))', align=CENTER)
        put(ws, f"G{r}", f'=IF(A{r}="","",A{r}-{S("today")})', '"D-"0;"D+"0;"D-day"', align=CENTER)
        put(ws, f"H{r}", f'=IF(A{r}="","",IF(AND(G{r}>=0,G{r}<={S("alert_days")}),B{r}&" D-"&G{r},""))')
    add_list_validation(ws, f"C{EVENT_FIRST}:C{last}", '"' + ",".join(s.EVENT_KINDS) + '"')
    add_list_validation(ws, f"E{EVENT_FIRST}:E{last}", f"={q(s.SETTINGS)}$L$3:$L$5")
    widths(ws, {"A": 11, "B": 30, "C": 7, "D": 13, "E": 8, "F": 9, "G": 8, "H": 30})
    ws.freeze_panes = "A4"


# ---------------------------------------------------------------- 현금흐름
CF_FIRST = 11


def build_cashflow(ws, pnl: dict[str, int]) -> None:
    title(ws, "💧 현금흐름 예측 (향후 6개월)", "정기 유입·유출은 손익 평균, 비정기 항목은 '일정' 시트의 유입/유출을 반영합니다.")
    p = lambda key, col: f"{q(s.PNL)}{col}{pnl[key]}"
    assumptions = [
        ("기초 가용현금 (기준월 말, 즉시 현금성 − 즉시 부채)", f"={q(s.BALANCE)}B{BS['cash_available']}"),
        ("월 정기 유입 (급여·이자배당·부수입 12개월 평균)", f"=({p('cat:급여', 'N')}+{p('cat:이자배당', 'N')}+{p('cat:부수입', 'N')})/12"),
        ("월 정기 유출 (고정비+변동비 12개월 평균)", f"=({p('고정비 합계', 'N')}+{p('변동비 합계', 'N')})/12"),
        ("월 자본이동 (저축·투자·원금상환, 최근 3개월 평균)", f"={p('자본이동 합계', 'P')}"),
        ("최소 유지잔고 (설정)", f"={S('min_cash')}"),
    ]
    section(ws, 3, "가정", 1, 2)
    for i, (label, formula) in enumerate(assumptions):
        put(ws, f"A{4 + i}", label)
        put(ws, f"B{4 + i}", formula, MONEY)
    write_header(ws, 10, ["월", "정기 유입", "일정 유입", "정기 유출", "자본이동", "일정 유출", "순현금흐름", "예상 잔고", "상태", "(알림용)"])
    ev = lambda col: f"{q(s.EVENTS)}${col}${EVENT_FIRST}:${col}${EVENT_FIRST + s.EVENT_ROWS - 1}"
    for k in range(6):
        r = CF_FIRST + k
        put(ws, f"A{r}", f"={month_offset(k + 1)}", align=CENTER)
        put(ws, f"B{r}", "=$B$5", MONEY)
        put(ws, f"C{r}", f'=SUMIFS({ev("D")},{ev("F")},A{r},{ev("C")},"유입",{ev("E")},{S("crit")})', MONEY)
        put(ws, f"D{r}", "=$B$6", MONEY)
        put(ws, f"E{r}", "=$B$7", MONEY)
        put(ws, f"F{r}", f'=SUMIFS({ev("D")},{ev("F")},A{r},{ev("C")},"유출",{ev("E")},{S("crit")})', MONEY)
        put(ws, f"G{r}", f"=B{r}+C{r}-D{r}-E{r}-F{r}", MONEY)
        put(ws, f"H{r}", f"={'$B$4' if k == 0 else f'H{r - 1}'}+G{r}", MONEY, font=F_BOLD)
        put(ws, f"I{r}", f'=IF(H{r}<$B$8,"🔴 부족","✅ 정상")', align=CENTER)
        put(ws, f"J{r}", f'=IF(H{r}<$B$8,A{r}&" "&TEXT(H{r},"#,##0")&"원","")', font=F_NOTE)
    status_colors(ws, f"I{CF_FIRST}:I{CF_FIRST + 5}")
    widths(ws, {"A": 50, "B": 15, "C": 13, "D": 13, "E": 13, "F": 13, "G": 14, "H": 15, "I": 10, "J": 22})


# ---------------------------------------------------------------- 대시보드
CARD_COLS = ["B", "D", "F", "H", "J"]


def build_dashboard(ws, base_month: str, pnl: dict[str, int]) -> None:
    ws.sheet_view.showGridLines = False
    widths(ws, {"A": 2, **{get_column_letter(c): 14 for c in range(2, 12)}, "L": 2})
    ws.merge_cells("B1:K1")
    ws["B1"] = "🏠 우리집 주식회사 · 자산관리 대시보드"
    ws["B1"].font = Font(name=FONT_NAME, size=20, bold=True, color=NAVY)
    ws.row_dimensions[1].height = 34
    ws.merge_cells("B2:K2")
    ws["B2"] = f'="기준월 "&{S("base")}&" 결산  ·  보기: "&{S("view")}&"  ·  금액 단위: 원"'
    ws["B2"].font = F_NOTE

    put(ws, "B4", "기준월 (yyyy-mm)", font=F_BOLD, align=CENTER)
    put(ws, "C4", base_month, "@", font=Font(name=FONT_NAME, size=11, bold=True, color=INPUT_BLUE), fill=FILL_KEY, align=CENTER)
    put(ws, "D4", "보기", font=F_BOLD, align=CENTER)
    put(ws, "E4", "전체", font=Font(name=FONT_NAME, size=11, bold=True, color=INPUT_BLUE), fill=FILL_KEY, align=CENTER)
    add_list_validation(ws, "E4", f"={q(s.SETTINGS)}$F$3:$F$6")
    put(ws, "G4", "오늘", font=F_BOLD, align=CENTER)
    put(ws, "H4", f"={S('today')}", DATE_FMT, align=CENTER)
    ws.merge_cells("I4:K4")
    ws["I4"] = "← 노란 칸을 바꾸면 모든 시트가 다시 계산됩니다"
    ws["I4"].font = F_NOTE

    pr = lambda key, col="M": f"{q(s.PNL)}{col}{pnl[key]}"
    bs = lambda key, col="B": f"{q(s.BALANCE)}{col}{BS[key]}"
    bud = lambda col: f"{q(s.BUDGET)}{col}{BUDGET_TOTAL_MONTHLY}"
    over_count = f'COUNTIF({q(s.BUDGET)}I{BUDGET_FIRST}:I{BUDGET_LAST},"*초과*")'
    emergency_months = f"IF({pr('필수지출', 'P')}=0,0,{bs('emergency')}/{pr('필수지출', 'P')})"
    goals_delay = f"{q(s.GOALS)}B{GOAL_SUM + 2}"
    joint = f'{S("view")}="공동"'   # 공동 계좌는 소득이 거의 없어 저축률이 의미 없다
    cards = [
        # (제목, 값 수식, 서식, 보조 문구, 상태)
        ("순자산", f"={bs('net')}", MONEY,
         f'="약 "&TEXT({bs("net")}/100000000,"0.00")&"억원"',
         f'=IF({bs("net", "D")}>=0,"✅ 전월 대비 증가 ","⚠ 전월 대비 감소 ")&TEXT({bs("net", "D")},"+#,##0;-#,##0")'),
        ("저축률 (이번 달)", f'=IF({joint},"",{pr("저축률")})', PCT,
         f'=IF({joint},"공동 보기는 직접 소득이 없어 계산하지 않음","목표 "&TEXT({S("t_saving")},"0%")&" · 12개월 "&TEXT({pr("저축률", "N")},"0.0%"))',
         f'=IF({joint},"- 해당 없음",IF({pr("소득 합계")}=0,"- 소득 데이터 없음",IF({pr("저축률")}>={S("t_saving")},"✅ 달성","⚠ 미달")))'),
        ("월 투자 납입액", f"={pr('투자 납입액 (투자+연금)')}", MONEY,
         f'="목표 "&TEXT({S("t_invest_view")},"#,##0")&IF({joint},""," · 납입률 "&TEXT({pr("투자 납입률")},"0%"))',
         f'=IF({pr("투자 납입액 (투자+연금)")}>={S("t_invest_view")},"✅ 달성","⚠ 미달 "&TEXT({S("t_invest_view")}-{pr("투자 납입액 (투자+연금)")},"#,##0"))'),
        ("투자+연금 자산", f"={bs('invest')}", MONEY,
         f'="총자산의 "&TEXT(IF({bs("total_assets")}=0,0,{bs("invest")}/{bs("total_assets")}),"0.0%")',
         f'=IF({bs("invest", "D")}>=0,"✅ 증가 ","⚠ 감소 ")&TEXT({bs("invest", "D")},"+#,##0;-#,##0")'),
        ("소비 예산 집행률", f"={bud('G')}", PCT,
         f'=IF({S("view")}="전체","실적 "&TEXT({bud("F")},"#,##0")&" / 예산 "&TEXT({bud("E")},"#,##0"),"가계 예산 중 "&{S("view")}&" 사용분 "&TEXT({bud("F")},"#,##0"))',
         f'=IF({over_count}>0,"🔴 초과 카테고리 "&{over_count}&"개",IF({bud("G")}>=0.9,"⚠ 주의","✅ 양호"))'),
        ("비상자금", f"={emergency_months}", '0.0"개월"',
         f'="목표 "&{S("t_emergency")}&"개월 · "&TEXT({bs("emergency")},"#,##0")&"원"',
         f'=IF({emergency_months}>={S("t_emergency")},"✅ 달성","⚠ 미달")'),
        ("부채비율", f"={bs('debt_ratio')}", PCT,
         f'="상한 "&TEXT({S("t_debt")},"0%")&" · 부채 "&TEXT({bs("liabilities")}/100000000,"0.00")&"억"',
         f'=IF({bs("debt_ratio")}<={S("t_debt")},"✅ 양호","⚠ 주의")'),
        ("DSR", f"={q(s.DEBT)}B{DEBT_DSR}", PCT,
         f'="상한 "&TEXT({S("t_dsr")},"0%")&" · 월 원리금 "&TEXT({q(s.DEBT)}B{DEBT_SUM + 1},"#,##0")',
         f'=IF({q(s.DEBT)}B{DEBT_DSR}<={S("t_dsr")},"✅ 양호","⚠ 주의")'),
        ("목표 달성률 (가중)", f"={q(s.GOALS)}B{GOAL_SUM}", PCT,
         f'="노후 준비율 "&TEXT({q(s.GOALS)}B{GOAL_SUM + 1},"0%")',
         f'=IF({goals_delay}=0,"✅ 모두 순항","⚠ 지연 "&{goals_delay}&"건")'),
        ("재무자립도", f"=IF({pr('소비지출 합계', 'O')}=0,0,{pr('cat:이자배당', 'O')}/{pr('소비지출 합계', 'O')})", PCT,
         f'="월 수동소득 "&TEXT({pr("cat:이자배당", "O")},"#,##0")&"원"',
         '="장기 목표 100% (수동소득 ≥ 생활비)"'),
    ]
    for idx, (label, value, fmt, sub, status) in enumerate(cards):
        top = 6 if idx < 5 else 11
        c1 = CARD_COLS[idx % 5]
        c2 = get_column_letter(column_index_from_string(c1) + 1)
        for offset, (content, font, number_format) in enumerate([
            (label, Font(name=FONT_NAME, size=10, bold=True, color="475467"), None),
            (value, Font(name=FONT_NAME, size=17, bold=True, color=NAVY), fmt),
            (sub, Font(name=FONT_NAME, size=8, color="667085"), None),
            (status, Font(name=FONT_NAME, size=9, bold=True), None),
        ]):
            r = top + offset
            ws.merge_cells(f"{c1}{r}:{c2}{r}")
            cell = ws[f"{c1}{r}"]
            cell.value = content
            cell.font = font
            cell.alignment = CENTER
            if number_format:
                cell.number_format = number_format
            for col in (c1, c2):
                ws[f"{col}{r}"].fill = FILL_CARD
                ws[f"{col}{r}"].border = Border(
                    left=THIN if col == c1 else None, right=THIN if col == c2 else None,
                    top=THIN if offset == 0 else None, bottom=THIN if offset == 3 else None)
        ws.row_dimensions[top + 1].height = 30
        status_colors(ws, f"{c1}{top + 3}")

    # 알림
    ws.merge_cells("B16:F16")
    put(ws, "B16", "🔔 이번 달 알림 (내부통제)", font=F_HEADER, fill=FILL_HEADER)
    join = lambda rng: f'_xlfn.TEXTJOIN(", ",TRUE,{rng})'
    inv_actual, inv_target = pr("투자 납입액 (투자+연금)"), S("t_invest_view")
    alloc_status = f"{q(s.INVEST)}F{INV['alloc_first']}:F{INV['alloc_total'] - 1}"
    alloc_names = f"{q(s.INVEST)}H{INV['alloc_first']}:H{INV['alloc_total'] - 1}"
    event_rng = lambda col: f"{q(s.EVENTS)}{col}{EVENT_FIRST}:{col}{EVENT_FIRST + s.EVENT_ROWS - 1}"
    goal_names = f"{q(s.GOALS)}P{GOAL_FIRST}:P{GOAL_FIRST + s.GOAL_ROWS - 1}"
    budget_names = f"{q(s.BUDGET)}M{BUDGET_FIRST}:M{BUDGET_LAST}"
    cf_status = f"{q(s.CASHFLOW)}I{CF_FIRST}:I{CF_FIRST + 5}"
    cf_names = f"{q(s.CASHFLOW)}J{CF_FIRST}:J{CF_FIRST + 5}"
    alerts = [
        f'=IF({over_count}>0,"🔴 예산 초과: "&{join(budget_names)},"")',
        f'=IF(AND(NOT({joint}),{pr("소득 합계")}>0,{pr("저축률")}<{S("t_saving")}),"⚠ 저축률 "&TEXT({pr("저축률")},"0.0%")&" — 목표 "&TEXT({S("t_saving")},"0%")&" 미달","")',
        f'=IF({inv_actual}<{inv_target},"⚠ 투자 납입 "&TEXT({inv_target}-{inv_actual},"#,##0")&"원 부족 (목표 "&TEXT({inv_target},"#,##0")&")","")',
        f'=IF(AND({pr("필수지출", "P")}>0,{emergency_months}<{S("t_emergency")}),"⚠ 비상자금 "&TEXT({emergency_months},"0.0")&"개월 — 목표까지 "&TEXT(({S("t_emergency")}-{emergency_months})*{pr("필수지출", "P")},"#,##0")&"원 더 필요","")',
        f'=IF(AND({S("view")}="전체",COUNTIF({alloc_status},"*리밸런싱*")>0),"⚖ 리밸런싱 검토: "&{join(alloc_names)},"")',
        f'=IF(OR({bs("debt_ratio")}>{S("t_debt")},{q(s.DEBT)}B{DEBT_DSR}>{S("t_dsr")}),"⚠ 부채 관리: 부채비율 "&TEXT({bs("debt_ratio")},"0%")&" · DSR "&TEXT({q(s.DEBT)}B{DEBT_DSR},"0%"),"")',
        f'=IF(COUNTIF({event_rng("H")},"?*")>0,"🗓 다가오는 일정: "&{join(event_rng("H"))},"")',
        f'=IF({goals_delay}>0,"🎯 목표 지연: "&{join(goal_names)},"")',
        f'=IF(AND({q(s.CASHFLOW)}$B$5>0,COUNTIF({cf_status},"*부족*")>0),"🔴 잔고 부족 예상: "&{join(cf_names)},"")',
        f'=IF(AND(COUNTA({q(s.INSURANCE)}A{INS_FIRST}:A{INS_FIRST + s.INSURANCE_ROWS - 1})>0,{q(s.INSURANCE)}B{INS_GAPS}>0),"🛡 보장 공백 "&{q(s.INSURANCE)}B{INS_GAPS}&"건 — 보험 탭 확인","")',
        f'=IF({pr("미분류 금액")}>0,"❓ 미분류 거래 "&TEXT({pr("미분류 금액")},"#,##0")&"원 — 카테고리 지정 필요","")',
    ]
    # 숨김 열 N에 알림 후보를, O에 누적 개수를 두고 보이는 칸은 k번째 알림을 가져온다 → 빈 줄 없이 위로 모임
    first, last = 17, 16 + len(alerts)
    for i, formula in enumerate(alerts):
        r = first + i
        ws[f"N{r}"] = formula
        ws[f"O{r}"] = f'=IF(N{r}="",0,1)+N(O{r - 1})'
        ws.merge_cells(f"B{r}:F{r}")
        put(ws, f"B{r}", f'=IFERROR(INDEX($N${first}:$N${last},MATCH({i + 1},$O${first}:$O${last},0)),"")',
            font=Font(name=FONT_NAME, size=9), align=Alignment(vertical="center", wrap_text=True))
        for col in "CDEF":
            ws[f"{col}{r}"].border = BOX
        ws.row_dimensions[r].height = 26
    r = 17 + len(alerts)
    ws.merge_cells(f"B{r}:F{r}")
    put(ws, f"B{r}", f'=IF(MAX(O{first}:O{last})=0,"✅ 이상 없음 — 이번 달도 잘 운영되었습니다","")', font=F_BOLD)
    ws.column_dimensions["N"].hidden = True
    ws.column_dimensions["O"].hidden = True

    # 구성원별 순자산
    ws.merge_cells("H16:K16")
    put(ws, "H16", "👨‍👩‍👧 구성원별 순자산 (기준월)", font=F_HEADER, fill=FILL_HEADER)
    for c, h in zip("HIJK", ["구성원", "자산", "부채", "순자산"]):
        put(ws, f"{c}17", h, font=F_BOLD, fill=FILL_SECTION, align=CENTER)
    for i in range(4):
        r, src = 18 + i, BS["member_first"] + i
        font = F_BOLD if i == 3 else F_BASE
        for c, scol in zip("HIJK", "ABCD"):
            put(ws, f"{c}{r}", f"={q(s.BALANCE)}{scol}{src}", None if c == "H" else MONEY, font=font,
                align=CENTER if c == "H" else None)

    # 목표 진척
    ws.merge_cells("H23:K23")
    put(ws, "H23", "🎯 목표 진척", font=F_HEADER, fill=FILL_HEADER)
    for c, h in zip("HIJK", ["목표", "진척률", "상태", "필요 월적립"]):
        put(ws, f"{c}24", h, font=F_BOLD, fill=FILL_SECTION, align=CENTER)
    for i in range(5):
        r, src = 25 + i, GOAL_FIRST + i
        put(ws, f"H{r}", f'=IF({q(s.GOALS)}A{src}="","",{q(s.GOALS)}A{src})', font=Font(name=FONT_NAME, size=9))
        put(ws, f"I{r}", f'=IF(H{r}="","",{q(s.GOALS)}J{src})', PCT, align=CENTER)
        put(ws, f"J{r}", f'=IF(H{r}="","",{q(s.GOALS)}L{src})', align=CENTER)
        put(ws, f"K{r}", f'=IF(H{r}="","",{q(s.GOALS)}N{src})', MONEY)
    status_colors(ws, "J25:J29")
    ws.freeze_panes = "A5"


def add_charts(wb) -> None:
    """대시보드 차트 4종. openpyxl은 기존 파일을 열 때 차트를 보존하지 못하므로
    가져오기 도구가 저장 직전에 이 함수를 다시 호출해 차트를 복원한다."""
    ws = wb[s.DASHBOARD]
    ws._charts = []
    bal, pnl_ws, bud, inv = wb[s.BALANCE], wb[s.PNL], wb[s.BUDGET], wb[s.INVEST]

    line = LineChart()
    line.title = "순자산·투자자산 추이 (12개월)"
    line.y_axis.numFmt = '#,##0,,"백만"'
    line.height, line.width = 7.5, 13.2
    line.add_data(Reference(bal, min_col=4, max_col=5, min_row=BS["trend_first"] - 1, max_row=BS["trend_last"]), titles_from_data=True)
    line.set_categories(Reference(bal, min_col=1, min_row=BS["trend_first"], max_row=BS["trend_last"]))
    ws.add_chart(line, "B32")

    pnl_rows = _pnl_rows_from_sheet(pnl_ws)
    bar = BarChart()
    bar.type = "col"
    bar.title = "월별 소득 · 소비 · 투자 납입"
    bar.y_axis.numFmt = '#,##0,,"백만"'
    bar.height, bar.width = 7.5, 13.2
    for key in ["소득 합계", "소비지출 합계", "투자 납입액 (투자+연금)"]:
        bar.add_data(Reference(pnl_ws, min_col=1, max_col=13, min_row=pnl_rows[key], max_row=pnl_rows[key]),
                     from_rows=True, titles_from_data=True)
    bar.set_categories(Reference(pnl_ws, min_col=2, max_col=13, min_row=3, max_row=3))
    ws.add_chart(bar, "H32")

    monthly = 0
    while monthly < BUDGET_LAST - BUDGET_FIRST + 1 and bud.cell(BUDGET_FIRST + monthly, 3).value == "월":
        monthly += 1
    monthly = max(1, monthly)
    budget = BarChart()
    budget.type = "bar"
    budget.title = "이번 달 예산 vs 실적"
    budget.x_axis.scaling.orientation = "maxMin"
    budget.y_axis.numFmt = '#,##0,"천"'
    budget.height, budget.width = 9.5, 13.2
    budget.add_data(Reference(bud, min_col=5, max_col=6, min_row=3, max_row=BUDGET_FIRST + monthly - 1), titles_from_data=True)
    budget.set_categories(Reference(bud, min_col=1, min_row=BUDGET_FIRST, max_row=BUDGET_FIRST + monthly - 1))
    ws.add_chart(budget, "B48")

    alloc = BarChart()
    alloc.type = "col"
    alloc.title = "자산배분: 목표 vs 현재"
    alloc.y_axis.numFmt = "0%"
    alloc.height, alloc.width = 9.5, 13.2
    alloc.add_data(Reference(inv, min_col=2, max_col=2, min_row=3, max_row=INV["alloc_total"] - 1), titles_from_data=True)
    alloc.add_data(Reference(inv, min_col=4, max_col=4, min_row=3, max_row=INV["alloc_total"] - 1), titles_from_data=True)
    alloc.set_categories(Reference(inv, min_col=1, min_row=INV["alloc_first"], max_row=INV["alloc_total"] - 1))
    ws.add_chart(alloc, "H48")


def _pnl_rows_from_sheet(ws) -> dict[str, int]:
    return {str(ws.cell(row=r, column=1).value).strip(): r for r in range(4, ws.max_row + 1) if ws.cell(row=r, column=1).value}


# ---------------------------------------------------------------- 사용법
GUIDE_LINES = [
    ("우리집 주식회사 자산관리 대시보드 - 사용법", "title"),
    ("가정을 기업처럼: 재무상태표(얼마 가졌나) · 손익계산서(얼마 남나) · 현금흐름(모자라지 않나) · 예산(계획대로 쓰나) · 목표(어디까지 왔나) · 리스크(버틸 수 있나)", "note"),
    ("", None),
    ("■ 색 규칙", "section"),
    ("파란 글씨 = 직접 입력하는 칸 · 검정 글씨 = 수식(수정 금지) · 노란 칸 = 핵심 설정값 · 파란 헤더 = 입력 시트 열 · 남색 헤더 = 자동 계산 열", None),
    ("", None),
    ("■ 처음 시작할 때 (1회, 약 1시간)", "section"),
    ("1. [계좌] 가족의 모든 계좌·자산·부채를 등록 (계좌ID는 A01, I01처럼 짧고 고유하게)", None),
    ("2. [스냅샷] 지난달 말 기준 계좌별 잔액 입력 → 재무상태표·순자산이 바로 나옵니다", None),
    ("3. [예산] 카테고리별 월 예산(비정기비는 연 예산) 확정 - 부부가 함께 정하세요", None),
    ("4. [투자] 보유 종목·목표 자산배분, [부채] 대출 금리·만기, [목표] 재무 목표, [보험] 보장 내역 입력", None),
    ("5. [설정] 목표 저축률·비상자금 개월·월 투자 납입 목표 등 '경영 목표' 확인", None),
    ("", None),
    ("■ 운영 리듬 (거버넌스)", "section"),
    ("주간 10분: 카드·은행 CSV 가져오기 → [거래내역]에서 '미분류' 카테고리 지정", None),
    ("월말 30분 (월간 결산): 새 달 스냅샷 생성(new-month) → 잔액 갱신 → 대시보드 기준월 변경 → 알림 확인 → 다음 달 예산 조정", None),
    ("분기 1시간 (이사회): 리밸런싱 · 목표 진척 · 보험/구독 점검", None),
    ("연 1회 (가족 주총): 연간 결산, 내년 목표·예산 수립, 연말정산·절세 한도 점검", None),
    ("", None),
    ("■ 자동화 (python -m household_finance ...)", "section"),
    ("import   : 카드사/은행 CSV(엑셀에서 CSV로 저장)를 읽어 분류규칙으로 자동 분류, 중복 제거 후 거래내역에 추가", None),
    ("new-month: 지난달 스냅샷을 복사해 새 달 행을 만들고 대시보드 기준월을 바꿈 (잔액만 고치면 됨)", None),
    ("build    : 새 빈 템플릿(--blank) 또는 샘플 파일 생성", None),
    ("구글 시트: 파일 업로드 후 그대로 사용 가능. 투자 현재가에 =GOOGLEFINANCE(\"KRX:005930\") 형태로 시세 자동 반영 가능", None),
    ("주의: 도구로 저장하면 대시보드 차트 4종은 자동 복원되지만, 직접 추가한 차트/서식은 사라질 수 있습니다", "note"),
    ("", None),
    ("■ 구성원별 보기", "section"),
    ("대시보드 E4에서 전체/본인/배우자/공동 선택 → 손익·예산 실적·재무상태표·투자 비중이 해당 구성원 기준으로 바뀝니다", None),
    ("개인 보기에는 '공동' 항목이 포함되지 않습니다. 구성원별 순자산 표는 항상 세 구성원을 모두 보여줍니다", None),
    ("", None),
    ("■ 계산 기준", "section"),
    ("저축률 = (소득 − 소비지출) ÷ 소득. 저축·투자·대출 원금상환은 '자본이동'이라 소비가 아닙니다", None),
    ("비상자금 = 즉시 인출 가능한 현금성 자산 ÷ 최근 3개월 평균 필수지출", None),
    ("부채비율 = 총부채 ÷ 총자산 · DSR = 연간 원리금 ÷ 최근 12개월 소득", None),
    ("목표 진척률 = 연결계좌 잔액 합 ÷ 목표금액 · 계획 진척률 = (오늘−시작일) ÷ (목표일−시작일)", None),
    ("재무자립도 = 월평균 이자·배당 ÷ 월평균 소비지출 (100%면 일하지 않아도 생활 유지)", None),
    ("기준값(30%, 6개월, 40% 등)은 일반적인 가이드라인이며 [설정]에서 가정에 맞게 바꾸세요", "note"),
]


def build_guide(ws, sample: bool) -> None:
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 2
    ws.column_dimensions["B"].width = 140
    lines = list(GUIDE_LINES)
    if sample:
        lines.insert(2, ("※ 이 파일은 가상의 3인 가구 샘플 데이터입니다. 실제 사용은 --blank 템플릿으로 시작하세요.", "note"))
    for i, (text, kind) in enumerate(lines, start=1):
        cell = ws.cell(row=i, column=2, value=text)
        cell.font = {"title": F_TITLE, "section": F_SECTION, "note": F_NOTE}.get(kind, F_BASE)
        cell.alignment = Alignment(wrap_text=True, vertical="center")


# ---------------------------------------------------------------- 진입점
def _rows(ds):
    """데이터셋 → 시트 생성기가 쓰는 행 튜플."""
    return {
        "accounts": [(a.id, a.name, a.institution, a.type, a.owner, a.liquidity, a.memo) for a in ds.accounts],
        "snapshots": [(x.month, x.account_id, x.amount) for x in ds.snapshots],
        "holdings": [(h.account_id, h.name, h.code, h.asset_class, h.qty, h.avg_price, h.price) for h in ds.holdings],
        "debts": [(d.name, d.account_id, d.rate, d.maturity, d.method, d.payment) for d in ds.debts],
        "goals": [(g.name, g.owner, g.target, g.start, g.end, *(list(g.accounts) + ["", "", ""])[:3]) for g in ds.goals],
        "insurances": [(p.insured, p.insurer, p.product, *[p.coverages.get(c, 0) for c in s.COVERAGES], p.premium,
                        p.maturity, p.renewable) for p in ds.insurances],
        "events": [(e.day, e.desc, e.kind, e.amount, e.member) for e in ds.events],
    }


def build_workbook(path: str | Path, sample: bool = True, base_month: str | None = None, dataset=None) -> Path:
    """스프레드시트 생성. dataset을 주면 그 데이터로(웹앱 → 엑셀 내보내기), 아니면 샘플 또는 빈 템플릿."""
    from household_finance.model import empty_dataset, sample_dataset

    path = Path(path)
    if dataset is None:
        if base_month is None and not sample:
            today = date.today()
            y, m = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
            base_month = f"{y}-{m:02d}"
        dataset = sample_dataset() if sample else empty_dataset(base_month)
    ds = dataset
    if base_month:
        ds.settings.base_month = base_month
    base_month = ds.settings.base_month
    rows = _rows(ds)

    wb = Workbook()
    wb.remove(wb.active)
    sheets = {name: wb.create_sheet(name) for name in s.SHEET_ORDER}

    build_settings(sheets[s.SETTINGS], ds.settings)
    build_categories(sheets[s.CATEGORIES], ds.categories)
    build_rules(sheets[s.RULES], ds.rules)
    build_accounts(sheets[s.ACCOUNTS], rows["accounts"])
    build_snapshot(sheets[s.SNAPSHOT], rows["snapshots"])
    build_transactions(sheets[s.TX], sorted(ds.transactions, key=lambda t: t.day))
    build_budget(sheets[s.BUDGET], ds.budgets)
    pnl = build_pnl(sheets[s.PNL])
    build_balance(sheets[s.BALANCE])
    build_invest(sheets[s.INVEST], rows["holdings"], pnl, ds.allocation)
    build_debt(sheets[s.DEBT], rows["debts"], pnl)
    build_goals(sheets[s.GOALS], rows["goals"], pnl)
    build_insurance(sheets[s.INSURANCE], rows["insurances"], pnl)
    build_events(sheets[s.EVENTS], rows["events"])
    build_cashflow(sheets[s.CASHFLOW], pnl)
    build_dashboard(sheets[s.DASHBOARD], base_month, pnl)
    build_guide(sheets[s.GUIDE], any(t.source == "샘플" for t in ds.transactions))   # 샘플이면 안내 문구 추가
    add_charts(wb)

    for name, ws in sheets.items():
        kind = ("dashboard" if name == s.DASHBOARD else "guide" if name == s.GUIDE else
                "input" if name in s.INPUT_SHEETS else "report" if name in s.REPORT_SHEETS else "master")
        ws.sheet_properties.tabColor = TAB_COLORS[kind]
    wb.active = 0
    wb.calculation.fullCalcOnLoad = True   # 엑셀이 열 때 모든 수식을 다시 계산
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path

