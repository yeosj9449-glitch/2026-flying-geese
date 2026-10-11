"""가정 자산관리 대시보드의 데이터 모델(시트 이름, 열 배치, 기준 정보).

스프레드시트 생성기(workbook.py), CSV 가져오기(importer.py), 이후 웹앱이 모두
이 파일 하나를 기준으로 삼는다 - 열 위치나 카테고리를 바꿀 때는 여기만 고친다.
"""

from __future__ import annotations

# ---------------------------------------------------------------- 시트 이름
DASHBOARD = "대시보드"
GUIDE = "사용법"
TX = "거래내역"
SNAPSHOT = "스냅샷"
ACCOUNTS = "계좌"
INVEST = "투자"
DEBT = "부채"
GOALS = "목표"
INSURANCE = "보험"
EVENTS = "일정"
BUDGET = "예산"
PNL = "손익"
BALANCE = "재무상태표"
CASHFLOW = "현금흐름"
SETTINGS = "설정"
CATEGORIES = "카테고리"
RULES = "분류규칙"

# 탭 순서: 대시보드 → 사용법 → 입력 시트 → 보고 시트 → 기준 정보
SHEET_ORDER = [
    DASHBOARD, GUIDE,
    TX, SNAPSHOT, ACCOUNTS, INVEST, DEBT, GOALS, INSURANCE, EVENTS, BUDGET,
    PNL, BALANCE, CASHFLOW,
    SETTINGS, CATEGORIES, RULES,
]
INPUT_SHEETS = {TX, SNAPSHOT, ACCOUNTS, INVEST, DEBT, GOALS, INSURANCE, EVENTS, BUDGET}
REPORT_SHEETS = {PNL, BALANCE, CASHFLOW}
MASTER_SHEETS = {SETTINGS, CATEGORIES, RULES}

# 수식이 참조하는 데이터 행 상한 (헤더 1행 + 데이터)
TX_MAX_ROW = 5000
SNAPSHOT_MAX_ROW = 3000
ACCOUNT_ROWS = 40          # 계좌 시트 2~41행
HOLDING_ROWS = 100
DEBT_ROWS = 10
GOAL_ROWS = 10
INSURANCE_ROWS = 10
EVENT_ROWS = 60

# ---------------------------------------------------------------- 구성원
OWNERS = ["본인", "배우자", "공동"]               # 거래·계좌 소유 단위
MEMBERS = ["본인", "배우자", "공동", "자녀"]      # 목표 담당·보험 피보험자
VIEW_OPTIONS = ["전체"] + OWNERS                  # 대시보드 '보기' 선택지

# ---------------------------------------------------------------- 카테고리
INCOME = "소득"
FIXED = "고정비"
VARIABLE = "변동비"
IRREGULAR = "비정기비"
CAPITAL = "자본이동"   # 저축·투자·원금상환 - 소비가 아니라 자산 간 이동
GROUPS = [INCOME, FIXED, VARIABLE, IRREGULAR, CAPITAL]
CONSUMPTION_GROUPS = [FIXED, VARIABLE, IRREGULAR]
UNCATEGORIZED = "미분류"

# (카테고리, 대분류, 필수지출 여부, 예산기준 월/연, 기본 예산)
# 비정기비는 연간 예산으로 관리하고 경과 월수만큼 안분해 비교한다.
CATEGORY_TABLE = [
    ("급여", INCOME, "N", "", 0),
    ("상여", INCOME, "N", "", 0),
    ("이자배당", INCOME, "N", "", 0),
    ("부수입", INCOME, "N", "", 0),
    ("주거관리비", FIXED, "Y", "월", 320_000),
    ("대출이자", FIXED, "Y", "월", 1_100_000),
    ("보험료", FIXED, "Y", "월", 400_000),
    ("통신비", FIXED, "Y", "월", 160_000),
    ("교육비", FIXED, "Y", "월", 550_000),
    ("구독료", FIXED, "N", "월", 50_000),
    ("식비", VARIABLE, "Y", "월", 900_000),
    ("외식", VARIABLE, "N", "월", 400_000),
    ("생활용품", VARIABLE, "Y", "월", 250_000),
    ("교통", VARIABLE, "Y", "월", 330_000),
    ("쇼핑", VARIABLE, "N", "월", 300_000),
    ("의료", VARIABLE, "Y", "월", 120_000),
    ("여가", VARIABLE, "N", "월", 200_000),
    ("용돈", VARIABLE, "N", "월", 600_000),
    ("경조사", IRREGULAR, "N", "연", 1_200_000),
    ("여행", IRREGULAR, "N", "연", 5_200_000),
    ("세금", IRREGULAR, "Y", "연", 1_500_000),
    ("명절", IRREGULAR, "N", "연", 1_800_000),
    ("투자이체", CAPITAL, "N", "", 0),
    ("연금납입", CAPITAL, "N", "", 0),
    ("저축이체", CAPITAL, "N", "", 0),
    ("대출원금상환", CAPITAL, "N", "", 0),
]
INVEST_CATEGORIES = ["투자이체", "연금납입"]   # '월 투자 납입액' KPI 집계 대상

# ---------------------------------------------------------------- 계좌
ACCOUNT_TYPES = ["현금성", "투자", "연금", "부동산", "기타자산", "부채"]
ASSET_TYPES = ACCOUNT_TYPES[:-1]
LIABILITY = "부채"
LIQUIDITY = ["즉시", "1년내", "장기"]
ASSET_CLASSES = ["국내주식", "해외주식", "채권", "현금성", "대체투자"]
DEFAULT_ALLOCATION = {"국내주식": 0.20, "해외주식": 0.45, "채권": 0.20, "현금성": 0.10, "대체투자": 0.05}
COVERAGES = ["사망", "실손", "암", "뇌·심장", "배상책임"]
EVENT_KINDS = ["유입", "유출", "알림"]

# ---------------------------------------------------------------- 자동 분류 규칙
# 거래 내용에 키워드가 포함되면 해당 카테고리로 분류 (위에서부터 먼저 맞는 규칙 적용).
DEFAULT_RULES = [
    ("급여", "급여"), ("상여", "상여"), ("성과급", "상여"),
    # '대출 이자'가 '이자'(이자배당)보다 먼저 와야 한다 - 먼저 맞는 규칙이 이긴다.
    ("대출 이자", "대출이자"), ("대출이자", "대출이자"),
    ("배당", "이자배당"), ("이자", "이자배당"), ("강의료", "부수입"),
    ("관리비", "주거관리비"),
    ("보험료", "보험료"), ("어린이보험", "보험료"),
    ("SKT", "통신비"), ("KT 통신", "통신비"), ("LG U+", "통신비"), ("인터넷", "통신비"),
    ("학원", "교육비"), ("학습지", "교육비"),
    ("넷플릭스", "구독료"), ("유튜브", "구독료"), ("쿠팡와우", "구독료"), ("멜론", "구독료"),
    ("이마트", "식비"), ("홈플러스", "식비"), ("롯데마트", "식비"), ("마켓컬리", "식비"),
    ("로켓프레시", "식비"), ("동네마트", "식비"), ("하나로마트", "식비"),
    ("배달의민족", "외식"), ("요기요", "외식"), ("쿠팡이츠", "외식"), ("스타벅스", "외식"),
    ("식당", "외식"), ("카페", "외식"),
    ("다이소", "생활용품"), ("쿠팡", "생활용품"),
    ("주유", "교통"), ("칼텍스", "교통"), ("카카오T", "교통"), ("티머니", "교통"), ("하이패스", "교통"),
    ("무신사", "쇼핑"), ("백화점", "쇼핑"), ("올리브영", "쇼핑"),
    ("병원", "의료"), ("의원", "의료"), ("소아과", "의료"), ("약국", "의료"),
    ("CGV", "여가"), ("메가박스", "여가"), ("교보문고", "여가"), ("골프", "여가"),
    ("용돈", "용돈"),
    ("축의금", "경조사"), ("조의금", "경조사"), ("여행", "여행"), ("항공", "여행"), ("호텔", "여행"),
    ("자동차세", "세금"), ("재산세", "세금"), ("지방세", "세금"),
    ("명절", "명절"), ("추석", "명절"), ("설날", "명절"),
    ("연금저축", "연금납입"), ("IRP", "연금납입"),
    ("ISA", "투자이체"), ("증권", "투자이체"),
    ("적금", "저축이체"), ("청약", "저축이체"),
    ("원금상환", "대출원금상환"),
]

# ---------------------------------------------------------------- 열 배치
# 거래내역: 사람이 입력하는 열 + 수식으로 채워지는 열(월/대분류/필수/월번호)
TX_COLUMNS = ["일자", "월", "내용", "금액", "카테고리", "대분류", "필수", "구성원", "결제수단", "출처", "메모", "월번호"]
TX_FORMULA_COLUMNS = {"월", "대분류", "필수", "월번호"}
SNAPSHOT_COLUMNS = ["월", "계좌ID", "금액", "계좌명", "유형", "소유자", "유동성"]
ACCOUNT_COLUMNS = ["계좌ID", "계좌명", "기관", "유형", "소유자", "유동성", "메모"]


def col_letter(columns: list[str], name: str) -> str:
    """열 이름 → 엑셀 열 문자 (A, B, ...)."""
    index = columns.index(name)
    return chr(ord("A") + index)


def tx_row_formulas(row: int) -> dict[str, str]:
    """거래내역 한 행의 수식 열. 생성기와 가져오기 도구가 같은 수식을 쓰도록 공유한다."""
    return {
        "월": f'=IF(A{row}="","",TEXT(A{row},"yyyy-mm"))',
        "대분류": f"=IF(E{row}=\"\",\"\",IFERROR(INDEX('{CATEGORIES}'!$B$2:$B$200,MATCH(E{row},'{CATEGORIES}'!$A$2:$A$200,0)),\"{UNCATEGORIZED}\"))",
        "필수": f"=IF(E{row}=\"\",\"\",IFERROR(INDEX('{CATEGORIES}'!$C$2:$C$200,MATCH(E{row},'{CATEGORIES}'!$A$2:$A$200,0)),\"N\"))",
        "월번호": f'=IF(A{row}="","",YEAR(A{row})*100+MONTH(A{row}))',
    }


def snapshot_row_formulas(row: int) -> dict[str, str]:
    """스냅샷 한 행의 조회 수식 (계좌 시트에서 이름·유형·소유자·유동성을 끌어온다)."""
    def lookup(col: str) -> str:
        return (f"=IF(B{row}=\"\",\"\",IFERROR(INDEX('{ACCOUNTS}'!${col}$2:${col}${ACCOUNT_ROWS + 1},"
                f"MATCH(B{row},'{ACCOUNTS}'!$A$2:$A${ACCOUNT_ROWS + 1},0)),\"?\"))")
    return {"계좌명": lookup("B"), "유형": lookup("D"), "소유자": lookup("E"), "유동성": lookup("F")}
