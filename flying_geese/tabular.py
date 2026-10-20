"""운영자가 엑셀/구글시트로 직접 관리하는 CSV 입력용 공용 파싱 유틸.

소싱 관리, 키워드, 인플루언서 데이터는 API가 아니라 사람이 손으로 채우는
표라서 표기가 들쭉날쭉하다(예: 날짜 2026.10.20 / 2026-10-20, 불리언 Y/예/O,
숫자 1,200). 행 하나의 표기 오류가 전체 로딩을 죽이지 않도록 모든 파서는
해석 불가 값을 None/기본값으로 돌려준다 - 기존 API 클라이언트들의
"행 하나의 결측 필드가 배치 전체를 죽이면 안 된다" 원칙과 동일하다.
"""
from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path

_TRUE_VALUES = {"y", "yes", "true", "1", "o", "예", "네", "있음", "가능", "확인", "v", "✓", "✔"}
_DATE_FORMATS = ("%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d", "%Y%m%d", "%Y. %m. %d", "%Y.%m.%d.")


def read_csv_rows(path: str | Path) -> list[dict[str, str]]:
    """CSV를 헤더 기준 dict 리스트로 읽는다.

    엑셀에서 'CSV UTF-8'로 저장하면 BOM이 붙으므로 utf-8-sig로 연다.
    헤더/값 앞뒤 공백은 제거하고, 완전히 빈 행은 건너뛴다.
    """
    with Path(path).open(encoding="utf-8-sig", newline="") as fp:
        reader = csv.DictReader(fp)
        rows = []
        for raw in reader:
            row = {
                (key or "").strip(): (value or "").strip()
                for key, value in raw.items()
                if key is not None
            }
            if any(row.values()):
                rows.append(row)
        return rows


def write_csv_rows(path: str | Path, headers: list[str], rows: list[dict]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _format_cell(row.get(key)) for key in headers})
    return path


def _format_cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Y" if value else "N"
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def pick(row: dict[str, str], *keys: str) -> str:
    """여러 후보 헤더 중 처음으로 값이 있는 칸을 돌려준다 (헤더 표기 변형 대응)."""
    for key in keys:
        value = row.get(key)
        if value:
            return value
    return ""


def parse_bool(value: str | None) -> bool:
    return (value or "").strip().lower() in _TRUE_VALUES


def parse_date(value: str | None) -> date | None:
    text = (value or "").strip()
    if not text:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_float(value: str | None) -> float | None:
    text = (value or "").strip().replace(",", "").replace("%", "")
    if not text:
        return None
    if text.startswith("<"):
        # 네이버 검색광고는 10 미만 검색량을 "< 10"으로 표기한다.
        return 0.0
    try:
        return float(text)
    except ValueError:
        return None


def parse_int(value: str | None) -> int | None:
    number = parse_float(value)
    return int(number) if number is not None else None


def split_list(value: str | None) -> list[str]:
    """'사과; 배, 감귤' 같은 다중 값 칸을 리스트로 쪼갠다."""
    text = (value or "").replace(";", ",").replace("/", ",")
    return [part.strip() for part in text.split(",") if part.strip()]
