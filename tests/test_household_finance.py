import zipfile
from datetime import date

import pytest
from openpyxl import load_workbook

from household_finance import schema as s
from household_finance.__main__ import main
from household_finance.importer import categorize, import_statement, new_month, read_statement
from household_finance.workbook import build_workbook

CARD_CSV = """신한카드 이용내역 조회
조회기간,2026.10.01~2026.10.10
이용일자,이용가맹점,이용금액,결제구분
2026.10.01,이마트 성수점,"85,400",일시불
2026.10.02,스타벅스 서울숲점,"6,500",일시불
2026.10.02,스타벅스 서울숲점,"6,500",일시불
2026.10.03,알수없는상점,"12,000",일시불
2026.10.04,무신사,"-39,000",취소
합계,,"70,400",
"""

BANK_CSV = """거래일자,적요,출금액,입금액,잔액
2026-10-05,주택담보대출 이자,"1,003,000",0,"5,000,000"
2026-10-25,한빛산업 급여,0,"4,850,000","9,850,000"
"""


@pytest.fixture
def rules():
    return list(s.DEFAULT_RULES)


def test_categorize_first_matching_rule_wins(rules):
    assert categorize("주택담보대출 이자", rules) == "대출이자"   # '이자'(이자배당)보다 먼저
    assert categorize("쿠팡 로켓프레시", rules) == "식비"          # '쿠팡'(생활용품)보다 먼저
    assert categorize("쿠팡와우 멤버십", rules) == "구독료"
    assert categorize("cgv 왕십리", rules) == "여가"               # 대소문자 무시
    assert categorize("알수없는상점", rules) == s.UNCATEGORIZED


def test_every_rule_points_to_a_known_category():
    categories = {row[0] for row in s.CATEGORY_TABLE}
    assert {cat for _, cat in s.DEFAULT_RULES} <= categories


def test_read_card_statement_cp949_with_preamble(tmp_path):
    path = tmp_path / "card.csv"
    path.write_bytes(CARD_CSV.encode("cp949"))
    rows, skipped = read_statement(path)
    assert [(r.day, r.desc, r.amount) for r in rows[:2]] == [
        (date(2026, 10, 1), "이마트 성수점", 85_400), (date(2026, 10, 2), "스타벅스 서울숲점", 6_500)]
    assert len(rows) == 4
    assert any("취소" in line for line in skipped)      # 음수(취소) 금액은 건너뜀
    assert any("합계" in line for line in skipped)


def test_read_bank_statement_splits_in_and_out(tmp_path):
    path = tmp_path / "bank.csv"
    path.write_text(BANK_CSV, encoding="utf-8-sig")
    rows, _ = read_statement(path)
    assert [(r.amount, r.is_income) for r in rows] == [(1_003_000, False), (4_850_000, True)]


def test_sample_workbook_structure(tmp_path):
    path = build_workbook(tmp_path / "sample.xlsx")
    wb = load_workbook(path)
    assert wb.sheetnames == s.SHEET_ORDER
    tx = wb[s.TX]
    assert tx["B2"].value.startswith("=IF(A2")                    # 월은 수식
    assert tx["F2"].value.startswith("=IF(E2")                    # 대분류도 수식
    assert wb[s.DASHBOARD]["C4"].value == "2026-09"
    with zipfile.ZipFile(path) as z:
        assert len([n for n in z.namelist() if n.startswith("xl/charts/chart")]) == 4


def test_import_adds_categorized_rows_and_skips_duplicates(tmp_path):
    book = build_workbook(tmp_path / "book.xlsx", sample=False, base_month="2026-10")
    card = tmp_path / "card.csv"
    card.write_bytes(CARD_CSV.encode("cp949"))

    first = import_statement(book, card, "배우자", "신한카드")
    assert len(first.added) == 4 and first.duplicates == 0
    assert [t.category for t in first.added] == ["식비", "외식", "외식", s.UNCATEGORIZED]
    assert len(first.uncategorized) == 1

    ws = load_workbook(book)[s.TX]
    assert ws["C2"].value == "이마트 성수점" and ws["H2"].value == "배우자" and ws["I2"].value == "신한카드"
    assert ws["F5"].value.startswith("=IF(E5")                    # 추가된 행에도 수식이 들어감
    with zipfile.ZipFile(book) as z:                               # 저장 후에도 대시보드 차트 유지
        assert len([n for n in z.namelist() if n.startswith("xl/charts/chart")]) == 4

    again = import_statement(book, card, "배우자", "신한카드")
    assert again.added == [] and again.duplicates == 4             # 같은 커피 2잔도 개수로 비교

    other_member = import_statement(book, card, "본인", dry_run=True)
    assert len(other_member.added) == 4                            # 다른 구성원이면 중복 아님


def test_import_rejects_unknown_member(tmp_path):
    book = build_workbook(tmp_path / "book.xlsx", sample=False)
    with pytest.raises(ValueError):
        import_statement(book, tmp_path / "x.csv", "자녀")


def test_new_month_copies_previous_balances(tmp_path):
    book = build_workbook(tmp_path / "book.xlsx")
    month, count = new_month(book)
    assert (month, count) == ("2026-10", 17)
    wb = load_workbook(book)
    ws = wb[s.SNAPSHOT]
    rows = [r for r in ws.iter_rows(min_row=2, values_only=True) if r[0]]
    sept = {r[1]: r[2] for r in rows if r[0] == "2026-09"}
    octo = {r[1]: r[2] for r in rows if r[0] == "2026-10"}
    assert octo == sept
    assert wb[s.DASHBOARD]["C4"].value == "2026-10"
    with pytest.raises(ValueError):
        new_month(book, "2026-10")


def test_cli_build_and_import(tmp_path, capsys):
    book = tmp_path / "cli.xlsx"
    assert main(["build", "--out", str(book), "--blank"]) == 0
    bank = tmp_path / "bank.csv"
    bank.write_text(BANK_CSV, encoding="utf-8")
    assert main(["import", str(book), str(bank), "--member", "공동"]) == 0
    out = capsys.readouterr().out
    assert "추가 2건" in out and "대출이자" in out and "급여" in out
