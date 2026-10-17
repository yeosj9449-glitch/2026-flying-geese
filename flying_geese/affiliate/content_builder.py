"""게시물 초안(Markdown) 생성.

쿠팡 파트너스 약관과 공정거래위원회 「추천·보증 등에 관한 표시·광고 심사지침」에
따라, 파트너스 링크가 포함된 게시물에는 경제적 대가를 받는다는 사실을 게시물
상단(첫 화면)에 명확히 표시해야 한다. 표기 문구 없이 초안을 만들 수 없게 막는다.

초안은 "자동 발행용"이 아니다. 상품 정보만 나열한 글은 검색 노출도 거의 없고
저품질/스팸 판정 위험이 크므로, 운영자가 직접 사용 후기·비교·사진을 채워 넣는
TODO 섹션을 남긴다.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from flying_geese.affiliate.coupang_partners_api import AffiliateProduct

DISCLOSURE = "이 포스팅은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다."


def build_post_draft(
    keyword: str,
    products: list[AffiliateProduct],
    disclosure: str = DISCLOSURE,
    today: date | None = None,
) -> str:
    if not disclosure.strip():
        raise ValueError("대가성 표기 문구(disclosure)는 생략할 수 없습니다.")
    if not products:
        raise ValueError(f"'{keyword}' 상품이 없어 초안을 만들 수 없습니다.")
    today = today or date.today()

    lines = [
        f"> {disclosure}",
        "",
        f"# {keyword} 추천 비교 ({today.year}년 {today.month}월)",
        "",
        "<!-- TODO(운영자): 이 상품군을 찾게 된 계기/직접 사용·구매 경험을 2~3문단으로 작성 -->",
        "",
        "## 한눈에 비교",
        "",
        "| 순위 | 상품 | 가격 | 로켓배송 |",
        "| --- | --- | --- | --- |",
    ]
    for rank, product in enumerate(products, start=1):
        rocket = "O" if product.is_rocket else "-"
        lines.append(
            f"| {rank} | [{product.product_name}]({product.product_url}) "
            f"| {product.product_price:,}원 | {rocket} |"
        )
    lines += ["", "## 상품별 상세", ""]
    for rank, product in enumerate(products, start=1):
        lines += [
            f"### {rank}. {product.product_name}",
            "",
            f"- 가격: {product.product_price:,}원 (작성일 기준, 변동 가능)",
            f"- 구매 링크: {product.product_url}",
            "",
            "<!-- TODO(운영자): 장단점, 추천 대상, 실사용 사진 -->",
            "",
        ]
    lines += [
        "## 마무리",
        "",
        "<!-- TODO(운영자): 어떤 사람에게 어떤 상품을 추천하는지 한 줄 결론 -->",
        "",
        f"> {disclosure}",
        "",
    ]
    return "\n".join(lines)


def _slug(keyword: str) -> str:
    return re.sub(r"[^\w가-힣]+", "-", keyword).strip("-") or "post"


def write_drafts(
    drafts: dict[str, str], output_dir: Path, today: date | None = None
) -> list[Path]:
    today = today or date.today()
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for keyword, body in drafts.items():
        path = output_dir / f"{today.isoformat()}_{_slug(keyword)}.md"
        path.write_text(body, encoding="utf-8")
        paths.append(path)
    return paths
