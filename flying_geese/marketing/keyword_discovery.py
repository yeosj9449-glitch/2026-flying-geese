"""네이버 검색광고 세부 키워드 발굴 · 등급화 · 누적 관리.

흐름:
  1) 대표 품목 × 수식어(유기농/아기/이유식/유아/선물세트)로 힌트 키워드 생성
  2) 검색광고 키워드도구(API 또는 화면에서 내려받은 CSV)로 연관 키워드 + 검색량/경쟁도 수집
  3) 제외어·의도(구매/정보)·타깃(키즈/프리미엄) 분류 → A 핵심 / B 테스트 / C 콘텐츠 / X 제외 등급화
  4) (선택) 네이버 쇼핑 상품 수로 포화도(상품 수 ÷ 월 검색량) 산정
  5) 키워드 DB(keyword_db.csv)에 누적 - 신규/급상승/급감 자동 표시, 운영자 메모는 보존

규칙은 data/marketing/keyword_rules.json에서 관리한다 (코드 수정 없이 품목/수식어 추가).
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from flying_geese.tabular import parse_float, pick, read_csv_rows, write_csv_rows

DEFAULT_MARKETING_DIR = Path(__file__).resolve().parents[2] / "data" / "marketing"

GRADE_CORE = "A 핵심"
GRADE_TEST = "B 테스트"
GRADE_CONTENT = "C 콘텐츠"
GRADE_EXCLUDE = "X 제외"
GRADE_ORDER = [GRADE_CORE, GRADE_TEST, GRADE_CONTENT, GRADE_EXCLUDE]

_COMP_WEIGHT = {"낮음": 1.0, "중간": 0.7, "높음": 0.4}
_COMP_ALIASES = {"low": "낮음", "mid": "중간", "medium": "중간", "high": "높음"}
SURGE_PCT = 30.0  # 직전 조회 대비 이 이상 증가하면 '급상승'
MAX_HINTS_PER_CALL = 5  # 검색광고 keywordstool hintKeywords 최대 개수


@dataclass
class KeywordRules:
    items: list[str]
    kid_modifiers: list[str]
    premium_modifiers: list[str]
    purchase_modifiers: list[str]
    info_modifiers: list[str]
    negative_words: list[str]
    gift_tokens: list[str]
    hint_modifiers: list[str]
    min_volume: int = 30
    max_core_volume: int = 20000

    @classmethod
    def load(cls, path: str | Path) -> "KeywordRules":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        data = {k: v for k, v in data.items() if not k.startswith("_")}
        return cls(**data)


@dataclass
class KeywordStat:
    keyword: str
    pc_volume: int
    mobile_volume: int
    comp_idx: str = ""  # 낮음 / 중간 / 높음
    monthly_clicks: float = 0.0
    avg_ad_depth: float | None = None  # 월평균 노출 광고 수
    shopping_products: int | None = None  # 네이버 쇼핑 상품 수 (포화도 산정용, 선택)

    @property
    def total_volume(self) -> int:
        return self.pc_volume + self.mobile_volume

    @property
    def saturation(self) -> float | None:
        """상품 수 ÷ 월 검색량. 클수록 검색 1회당 경쟁 상품이 많다(포화)."""
        if self.shopping_products is None:
            return None
        return self.shopping_products / max(self.total_volume, 1)


@dataclass
class ClassifiedKeyword:
    stat: KeywordStat
    grade: str
    reason: str
    item: str = ""
    is_kid: bool = False
    is_premium: bool = False
    is_purchase: bool = False
    is_info: bool = False
    is_gift: bool = False
    score: float = 0.0
    ad_group: str = ""
    bid_strategy: str = ""
    trend: str = ""  # 신규 / 급상승 / 급감 / 유지 (DB 누적 후 채움)
    prev_volume: int | None = None


@dataclass
class KeywordReport:
    keywords: list[ClassifiedKeyword] = field(default_factory=list)
    hints_used: list[str] = field(default_factory=list)
    source: str = ""

    def by_grade(self, grade: str) -> list[ClassifiedKeyword]:
        return [k for k in self.keywords if k.grade == grade]


def _norm(text: str) -> str:
    return text.replace(" ", "").lower()


def _contains_any(text: str, tokens: list[str]) -> str:
    """가장 긴 매칭 토큰을 돌려준다 (예: '미니사과'가 '사과'보다 우선)."""
    matches = [t for t in tokens if _norm(t) in text]
    return max(matches, key=len) if matches else ""


def saturation_label(saturation: float | None) -> str:
    if saturation is None:
        return "-"
    if saturation < 5:
        return "여유"
    if saturation < 20:
        return "보통"
    if saturation < 50:
        return "경쟁"
    return "포화"


def build_hint_keywords(rules: KeywordRules, items: list[str] | None = None) -> list[str]:
    """힌트 키워드 생성. 검색광고 API는 힌트에 공백을 허용하지 않으므로 붙여 쓴다."""
    hints: list[str] = []
    for item in items or rules.items:
        for modifier in rules.hint_modifiers:
            hint = _norm(f"{modifier}{item}")
            if hint not in hints:
                hints.append(hint)
    return hints


def chunk(values: list[str], size: int = MAX_HINTS_PER_CALL) -> list[list[str]]:
    return [values[i : i + size] for i in range(0, len(values), size)]


def stat_from_api_row(row: dict) -> KeywordStat:
    """검색광고 keywordstool 응답 행 → KeywordStat. 값이 '< 10'/null이어도 죽지 않는다."""

    def _num(value) -> float:
        if value is None:
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        return parse_float(str(value)) or 0.0

    comp = str(row.get("compIdx") or "").strip()
    return KeywordStat(
        keyword=str(row.get("relKeyword") or "").strip(),
        pc_volume=int(_num(row.get("monthlyPcQcCnt"))),
        mobile_volume=int(_num(row.get("monthlyMobileQcCnt"))),
        comp_idx=_COMP_ALIASES.get(comp.lower(), comp),
        monthly_clicks=_num(row.get("monthlyAvePcClkCnt")) + _num(row.get("monthlyAveMobileClkCnt")),
        avg_ad_depth=_num(row.get("plAvgDepth")) if row.get("plAvgDepth") is not None else None,
    )


def stat_from_csv_row(row: dict[str, str]) -> KeywordStat:
    """검색광고 관리시스템 키워드도구 화면에서 내려받은 CSV 행 → KeywordStat."""
    comp = pick(row, "경쟁정도", "경쟁 정도")
    return KeywordStat(
        keyword=pick(row, "연관키워드", "키워드"),
        pc_volume=int(parse_float(pick(row, "월간검색수(PC)", "월간검색수 PC", "PC")) or 0),
        mobile_volume=int(parse_float(pick(row, "월간검색수(모바일)", "월간검색수 모바일", "모바일")) or 0),
        comp_idx=_COMP_ALIASES.get(comp.lower(), comp),
        monthly_clicks=(parse_float(pick(row, "월평균클릭수(PC)")) or 0.0)
        + (parse_float(pick(row, "월평균클릭수(모바일)")) or 0.0),
        avg_ad_depth=parse_float(pick(row, "월평균노출 광고수", "월평균노출광고수")),
    )


def load_stats_file(path: str | Path) -> list[KeywordStat]:
    path = Path(path)
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        rows = data.get("keywordList", data) if isinstance(data, dict) else data
        return [s for s in (stat_from_api_row(r) for r in rows) if s.keyword]
    return [s for s in (stat_from_csv_row(r) for r in read_csv_rows(path)) if s.keyword]


def fetch_stats_from_api(client, hints: list[str], pause_sec: float = 0.3) -> list[KeywordStat]:
    """검색광고 API로 연관 키워드를 수집한다. 한 묶음이 실패해도 나머지는 계속 진행한다."""
    stats: list[KeywordStat] = []
    for group in chunk(hints):
        try:
            rows = client.keyword_stats(group)
        except Exception as exc:  # noqa: BLE001 - 묶음 단위 실패는 로그만 남기고 계속
            print(f"[keywords] 힌트 {group} 조회 실패: {exc}")
            continue
        stats.extend(s for s in (stat_from_api_row(r) for r in rows) if s.keyword)
        time.sleep(pause_sec)
    return dedupe(stats)


def dedupe(stats: list[KeywordStat]) -> list[KeywordStat]:
    seen: dict[str, KeywordStat] = {}
    for stat in stats:
        key = _norm(stat.keyword)
        if key not in seen or stat.total_volume > seen[key].total_volume:
            seen[key] = stat
    return list(seen.values())


def classify(stat: KeywordStat, rules: KeywordRules) -> ClassifiedKeyword:
    text = _norm(stat.keyword)
    negative = _contains_any(text, rules.negative_words)
    item = _contains_any(text, rules.items)
    kw = ClassifiedKeyword(stat=stat, grade=GRADE_EXCLUDE, reason="", item=item)
    kw.is_kid = bool(_contains_any(text, rules.kid_modifiers))
    kw.is_premium = bool(_contains_any(text, rules.premium_modifiers))
    kw.is_purchase = bool(_contains_any(text, rules.purchase_modifiers))
    kw.is_info = bool(_contains_any(text, rules.info_modifiers))
    kw.is_gift = bool(_contains_any(text, rules.gift_tokens))
    volume = stat.total_volume
    targeted = kw.is_kid or kw.is_premium

    if negative:
        kw.reason = f"제외어 포함({negative})"
    elif not item:
        kw.reason = "취급 품목 아님"
    elif kw.is_info:
        kw.grade, kw.reason = GRADE_CONTENT, "정보 탐색형 - 블로그/인스타 콘텐츠 주제로 활용"
    elif targeted:
        if volume < rules.min_volume:
            kw.grade, kw.reason = GRADE_TEST, "롱테일(검색량 적음) - 저입찰 묶음"
        elif stat.comp_idx == "높음" and volume > rules.max_core_volume:
            kw.grade, kw.reason = GRADE_TEST, "대형·고경쟁 - 일예산 상한 걸고 소액 테스트"
        else:
            kw.grade, kw.reason = GRADE_CORE, "타깃(키즈/프리미엄) 일치 + 적정 검색량"
    elif kw.is_purchase and stat.comp_idx != "높음" and volume >= rules.min_volume:
        kw.grade, kw.reason = GRADE_TEST, "일반 구매 키워드 - 타깃 외, 저경쟁이라 테스트 가치"
    else:
        kw.reason = "타깃 외 일반 키워드"

    kw.score = keyword_score(kw)
    kw.ad_group = ad_group_for(kw)
    kw.bid_strategy = bid_strategy_for(kw)
    return kw


def keyword_score(kw: ClassifiedKeyword) -> float:
    """같은 등급 안에서의 우선순위 점수 (검색량 × 경쟁도 × 타깃/의도 가중 ÷ 포화도)."""
    if kw.grade == GRADE_EXCLUDE:
        return 0.0
    score = math.log10(kw.stat.total_volume + 10) * 100  # 대형 키워드가 독식하지 않도록 로그 스케일
    score *= _COMP_WEIGHT.get(kw.stat.comp_idx, 0.7)
    if kw.is_kid:
        score *= 1.3
    if kw.is_premium:
        score *= 1.15
    if kw.is_purchase:
        score *= 1.2
    saturation = kw.stat.saturation
    if saturation is not None:
        score /= 1 + saturation / 50
    return round(score, 1)


def ad_group_for(kw: ClassifiedKeyword) -> str:
    if kw.grade in (GRADE_EXCLUDE, GRADE_CONTENT):
        return ""
    if kw.is_gift:
        return "선물세트"
    if "이유식" in _norm(kw.stat.keyword):
        return "이유식재료"
    suffix = "키즈" if kw.is_kid else ("프리미엄" if kw.is_premium else "일반")
    return f"{kw.item}_{suffix}"


def bid_strategy_for(kw: ClassifiedKeyword) -> str:
    if kw.grade == GRADE_CORE:
        return "중간 순위(3~5위) 목표, 2주 성과 보고 조정"
    if kw.grade == GRADE_TEST and "롱테일" in kw.reason:
        return "최저 입찰(70원)부터 시작"
    if kw.grade == GRADE_TEST:
        return "일 예산 상한 + 하위 순위 입찰로 소액 테스트"
    return ""


def classify_all(stats: list[KeywordStat], rules: KeywordRules) -> list[ClassifiedKeyword]:
    classified = [classify(s, rules) for s in dedupe(stats)]
    rank = {g: i for i, g in enumerate(GRADE_ORDER)}
    return sorted(classified, key=lambda k: (rank[k.grade], -k.score, k.stat.keyword))


# ---------------------------------------------------------------------------
# 키워드 DB 누적 (주 1회 실행 → 신규/급상승/급감 추적)
# ---------------------------------------------------------------------------
DB_HEADERS = [
    "키워드", "등급", "광고그룹", "최근검색량", "직전검색량", "변화율(%)", "경쟁정도", "포화도",
    "추세", "최초발견일", "최근조회일", "운영상태", "메모",
]


def update_keyword_db(db_path: Path, keywords: list[ClassifiedKeyword], today: date) -> Path:
    """키워드 DB를 갱신한다. 운영자가 쓰는 '운영상태'(예: 등록완료/보류)와 '메모'는 보존한다."""
    existing = {r["키워드"]: r for r in (read_csv_rows(db_path) if db_path.exists() else []) if r.get("키워드")}
    for kw in keywords:
        if kw.grade == GRADE_EXCLUDE:
            continue
        name = kw.stat.keyword
        prev = existing.get(name)
        volume = kw.stat.total_volume
        if prev is None:
            kw.trend, kw.prev_volume, first_seen = "신규", None, today.isoformat()
            ops_status, memo = "", ""
        else:
            first_seen = prev.get("최초발견일") or today.isoformat()
            ops_status, memo = prev.get("운영상태", ""), prev.get("메모", "")
            if prev.get("최근조회일") == today.isoformat():
                # 같은 날 재실행: 직전 값을 덮어쓰지 않도록 기존 비교 기준 유지
                prev_volume = int(parse_float(prev.get("직전검색량")) or 0) or None
                kw.trend = prev.get("추세", "유지")
            else:
                prev_volume = int(parse_float(prev.get("최근검색량")) or 0)
                kw.trend = _trend(prev_volume, volume)
            kw.prev_volume = prev_volume
        change = _change_pct(kw.prev_volume, volume)
        existing[name] = {
            "키워드": name, "등급": kw.grade, "광고그룹": kw.ad_group, "최근검색량": volume,
            "직전검색량": kw.prev_volume if kw.prev_volume is not None else "",
            "변화율(%)": "" if change is None else round(change, 1), "경쟁정도": kw.stat.comp_idx,
            "포화도": saturation_label(kw.stat.saturation), "추세": kw.trend, "최초발견일": first_seen,
            "최근조회일": today.isoformat(), "운영상태": ops_status, "메모": memo,
        }
    rank = {g: i for i, g in enumerate(GRADE_ORDER)}
    rows = sorted(existing.values(), key=lambda r: (rank.get(r.get("등급"), 9), -int(parse_float(str(r.get("최근검색량"))) or 0)))
    return write_csv_rows(db_path, DB_HEADERS, rows)


def _change_pct(prev: int | None, current: int) -> float | None:
    if not prev:
        return None
    return (current - prev) / prev * 100


def _trend(prev: int, current: int) -> str:
    change = _change_pct(prev, current)
    if change is None:
        return "유지"
    if change >= SURGE_PCT:
        return "급상승"
    if change <= -SURGE_PCT:
        return "급감"
    return "유지"
