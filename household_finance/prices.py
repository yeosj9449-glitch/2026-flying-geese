"""보유 종목 현재가 갱신.

두 가지 경로가 있다.
1. 자동 조회: 시세코드가 'KRX:005930'처럼 국내 6자리 코드인 종목을 네이버 금융 모바일 시세에서 읽는다.
   네이버가 공식 API로 제공하는 것이 아니어서 예고 없이 바뀌거나 막힐 수 있다 - 실패한 종목은
   기존 가격을 그대로 두고 실패 목록으로 알려 준다.
2. 시세 CSV 올리기: '시세코드(또는 종목명), 현재가' 두 열짜리 파일. 인터넷 사정과 관계없이 항상 쓸 수 있다.
"""

from __future__ import annotations

import csv
import io
import json
import re
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from household_finance.importer import _parse_amount

CODE_RE = re.compile(r"^(?:KRX:|KOSPI:|KOSDAQ:)?([0-9][0-9A-Z]{5})$", re.IGNORECASE)
NAVER_URL = "https://m.stock.naver.com/api/stock/{code}/basic"


def krx_code(code: str | None) -> str | None:
    """'KRX:005930' → '005930'. 국내 상장 코드가 아니면 None (예금·TDF 등은 자동 조회 대상 아님)."""
    m = CODE_RE.match((code or "").strip())
    return m.group(1).upper() if m else None


def parse_naver(payload: dict) -> float:
    """네이버 모바일 시세 응답에서 현재가(closePrice)를 꺼낸다. 형식이 다르면 ValueError."""
    candidates = [payload]
    if isinstance(payload.get("datas"), list):   # 실시간 polling 응답 형식
        candidates += payload["datas"]
    for item in candidates:
        price = _parse_amount(item.get("closePrice")) if isinstance(item, dict) else None
        if price:
            return float(price)
    raise ValueError("응답에 현재가(closePrice)가 없습니다.")


def fetch_naver(code: str, timeout: float = 5.0) -> float:
    req = urllib.request.Request(NAVER_URL.format(code=code), headers={"User-Agent": "Mozilla/5.0 household-finance"})
    with urllib.request.urlopen(req, timeout=timeout) as res:   # 시스템 프록시 설정을 그대로 따른다
        return parse_naver(json.loads(res.read().decode("utf-8")))


def _reason(exc: Exception) -> str:
    if isinstance(exc, (urllib.error.URLError, ConnectionError, TimeoutError, OSError)):
        return "시세 서버에 연결할 수 없음 (인터넷·방화벽 확인)"
    return str(exc) or type(exc).__name__


def refresh(holdings: list[dict], fetch: Callable[[str], float] = fetch_naver) -> dict:
    """holdings: [{id, name, code, price}] → {updated: [...], skipped: [...], failed: [...]}.
    같은 코드는 한 번만, 여러 코드는 동시에 조회한다 (응답 없는 서버를 종목 수만큼 기다리지 않도록)."""
    def one(code: str) -> float | Exception:
        try:
            return fetch(code)
        except Exception as exc:   # 네트워크·형식 오류 모두 해당 종목만 실패로 처리
            return exc

    codes = sorted({c for c in (krx_code(h.get("code")) for h in holdings) if c})
    with ThreadPoolExecutor(max_workers=8) as pool:
        cache = dict(zip(codes, pool.map(one, codes)))
    report = {"updated": [], "skipped": [], "failed": []}
    for h in holdings:
        code = krx_code(h.get("code"))
        if code is None:
            report["skipped"].append({"id": h["id"], "name": h["name"], "reason": "국내 상장 시세코드 없음"})
            continue
        got = cache[code]
        if isinstance(got, Exception):
            report["failed"].append({"id": h["id"], "name": h["name"], "code": code, "reason": _reason(got)})
        else:
            report["updated"].append({"id": h["id"], "name": h["name"], "code": code, "old": h.get("price"), "new": got})
    return report


def parse_price_csv(text: str) -> dict[str, float]:
    """시세 CSV → {시세코드 또는 종목명: 현재가}. 헤더: 시세코드/코드/종목명/종목 + 현재가/종가/가격."""
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        raise ValueError("빈 파일입니다.")
    header = [h.strip() for h in rows[0]]
    key_i = next((header.index(k) for k in ("시세코드", "코드", "code", "종목명", "종목", "name") if k in header), None)
    price_i = next((header.index(k) for k in ("현재가", "종가", "가격", "price") if k in header), None)
    if key_i is None or price_i is None:
        raise ValueError("'시세코드(또는 종목명)'와 '현재가' 열이 필요합니다.")
    out = {}
    for row in rows[1:]:
        if len(row) > max(key_i, price_i) and row[key_i].strip():
            price = _parse_amount(row[price_i])
            if price:
                out[row[key_i].strip()] = float(price)
    return out


def match_prices(holdings: list[dict], prices: dict[str, float]) -> dict:
    """CSV 값을 보유종목에 맞춘다: 시세코드(접두어 무시) → 종목명 순서로 찾는다."""
    by_code = {krx_code(k) or k.upper(): v for k, v in prices.items()}
    report = {"updated": [], "skipped": [], "failed": []}
    for h in holdings:
        code = krx_code(h.get("code"))
        price = by_code.get(code) if code else None
        if price is None:
            price = prices.get(h["name"])
        if price is None:
            report["skipped"].append({"id": h["id"], "name": h["name"], "reason": "파일에 없음"})
        else:
            report["updated"].append({"id": h["id"], "name": h["name"], "code": code, "old": h.get("price"), "new": price})
    return report
