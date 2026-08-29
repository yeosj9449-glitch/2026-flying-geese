#!/usr/bin/env python3
"""엑셀 품목 DB의 키워드별 네이버 검색광고 경쟁지수를 조회해 CSV로 저장한다.

사용 예:
    python scripts/fetch_competition_index.py \\
        --input 위탁판매_1월-12월_제철품목DB.xlsx \\
        --sheet 전체품목DB \\
        --output competition_result.csv

NAVER_SEARCHAD_API_KEY / NAVER_SEARCHAD_SECRET_KEY / NAVER_SEARCHAD_CUSTOMER_ID
환경변수(.env)가 설정되어 있어야 한다. 경쟁지수(compIdx)와 월간 검색량(PC+모바일)은
네이버 검색광고 keywordstool API가 제공하는 값을 그대로 사용한다 — 쿠팡/스마트스토어는
키워드별 상품 등록 수를 제공하는 공식 API가 없어(marketplace_rank.py 참고) 이
스크립트의 대상에서 제외했다.

[2026-08 기준] 원래는 compIdx를 검색량과 결합해 "블루오션 점수(검색량÷등록상품수)"를
계산하려 했으나, 등록상품수를 제공하던 네이버쇼핑 검색 API(/v1/search/shop.json)가
2026년 7월 31일 공식 종료되어 공식 대체 API가 없다. 따라서 실제 등록상품수 기반 경쟁
확인은 자동화할 수 없고, 이 스크립트의 compIdx는 1차 스크리닝용 참고 지표로만 사용한다.

/keywordstool 엔드포인트는 한 번에 최대 5개 키워드(hintKeywords)까지 조회 가능하며
초당 호출 제한이 있으므로 요청 사이에 짧은 딜레이(--delay)를 둔다. compIdx는
'낮음'/'중간'/'높음' 3단계 문자열로 반환되므로, 정렬·필터링이 쉽도록
competition_index_score(1/2/3)를 추가로 계산해 함께 저장한다.
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flying_geese.config import load_settings
from flying_geese.stage2_blue_ocean.naver_searchad import NaverSearchAdClient

CANDIDATE_KEYWORD_COLUMNS = [
    "세부품종",
    "품종",
    "품목명",
    "대표품목",
    "상품명",
    "키워드",
    "variety",
    "keyword",
    "item",
    "product_name",
]
BATCH_SIZE = 5  # keywordstool API는 hintKeywords를 5개까지 허용
PAREN_PATTERN = re.compile(r"\([^)]*\)")
COMPETITION_INDEX_SCORE = {"낮음": 1, "중간": 2, "높음": 3}  # 정렬/필터링용 서열화


def _normalize(keyword: str) -> str:
    return keyword.replace(" ", "").strip()


def clean_keyword(keyword: str) -> str:
    """'과메기(초)' → '과메기'처럼 괄호 및 괄호 안 내용을 제거한다.

    괄호를 제거하면 빈 문자열이 되는 경우(예: 키워드 전체가 괄호로만 구성)는
    원본 키워드를 그대로 검색어로 사용한다.
    """
    cleaned = PAREN_PATTERN.sub("", keyword).strip()
    return cleaned or keyword.strip()


def pick_keyword_column(df: pd.DataFrame, override: str | None) -> str:
    if override:
        if override not in df.columns:
            raise SystemExit(
                f"'{override}' 컬럼이 없습니다. 사용 가능한 컬럼: {list(df.columns)}"
            )
        return override
    for name in CANDIDATE_KEYWORD_COLUMNS:
        if name in df.columns:
            return name
    raise SystemExit(
        "키워드 컬럼을 자동으로 찾지 못했습니다. --keyword-column 옵션으로 지정하세요. "
        f"사용 가능한 컬럼: {list(df.columns)}"
    )


def chunked(items: list[str], size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def fetch_stats(
    client: NaverSearchAdClient, query_keywords: list[str], delay: float
) -> dict[str, dict]:
    """정리된(괄호 제거) 검색어 기준으로 API를 조회해 정규화된 검색어 → 응답 매핑을 반환한다."""
    stats: dict[str, dict] = {}
    for batch in chunked(query_keywords, BATCH_SIZE):
        result = client.keyword_stats(batch)
        by_norm_keyword = {
            _normalize(str(row.get("relKeyword", ""))): row for row in result
        }
        for kw in batch:
            row = by_norm_keyword.get(_normalize(kw))
            if row is not None:
                stats[_normalize(kw)] = row
        if delay:
            time.sleep(delay)
    return stats


def build_rows(raw_keywords: list[str], stats: dict[str, dict]) -> list[dict]:
    rows: list[dict] = []
    for raw in raw_keywords:
        query = clean_keyword(raw)
        row = stats.get(_normalize(query))
        if row is None:
            rows.append(
                {
                    "keyword": raw,
                    "query_keyword": query,
                    "monthly_pc_search": "",
                    "monthly_mobile_search": "",
                    "monthly_search_volume": "",
                    "competition_index": "",
                    "competition_index_score": "",
                    "note": "API 응답에 없음",
                }
            )
            continue
        comp_idx = row.get("compIdx", "")
        rows.append(
            {
                "keyword": raw,
                "query_keyword": query,
                "monthly_pc_search": row.get("monthlyPcQcCnt", ""),
                "monthly_mobile_search": row.get("monthlyMobileQcCnt", ""),
                "monthly_search_volume": NaverSearchAdClient.monthly_search_volume(row),
                "competition_index": comp_idx,
                "competition_index_score": COMPETITION_INDEX_SCORE.get(comp_idx, ""),
                "note": "" if query == raw else "괄호 제거 후 검색",
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="입력 엑셀 파일 경로")
    parser.add_argument("--sheet", required=True, help="시트 이름")
    parser.add_argument("--output", required=True, help="출력 CSV 경로")
    parser.add_argument(
        "--keyword-column", default=None, help="키워드로 사용할 컬럼명(생략 시 자동 탐지)"
    )
    parser.add_argument(
        "--delay", type=float, default=0.5, help="API 호출 간 대기 시간(초, 기본 0.5)"
    )
    args = parser.parse_args()

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")

    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit(f"입력 파일을 찾을 수 없습니다: {input_path}")

    settings = load_settings()
    if not settings.naver_searchad_ready():
        raise SystemExit(
            "NAVER_SEARCHAD_API_KEY / NAVER_SEARCHAD_SECRET_KEY / "
            "NAVER_SEARCHAD_CUSTOMER_ID 환경변수(.env)가 설정되어 있지 않습니다."
        )

    df = pd.read_excel(input_path, sheet_name=args.sheet)
    keyword_col = pick_keyword_column(df, args.keyword_column)
    raw_keywords = sorted(
        {str(v).strip() for v in df[keyword_col].dropna() if str(v).strip()}
    )
    if not raw_keywords:
        raise SystemExit(f"'{keyword_col}' 컬럼에서 키워드를 찾지 못했습니다.")

    query_keywords = sorted({clean_keyword(kw) for kw in raw_keywords})
    cleaned_count = sum(1 for kw in raw_keywords if clean_keyword(kw) != kw)
    print(
        f"'{keyword_col}' 컬럼에서 키워드 {len(raw_keywords)}개를 수집했습니다"
        f"(괄호 제거 대상 {cleaned_count}개, 실제 조회할 고유 검색어 {len(query_keywords)}개)."
    )

    client = NaverSearchAdClient(settings)
    stats = fetch_stats(client, query_keywords, args.delay)
    rows = build_rows(raw_keywords, stats)

    out_df = pd.DataFrame(rows)
    out_path = Path(args.output)
    out_df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"결과를 저장했습니다: {out_path} ({len(out_df)}행)")


if __name__ == "__main__":
    main()
