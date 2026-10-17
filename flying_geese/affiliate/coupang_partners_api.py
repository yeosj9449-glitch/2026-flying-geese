"""쿠팡 파트너스 Open API - 상품 검색 / 딥링크 생성 / 수수료 리포트.

https://api-gateway.coupang.com/v2/providers/affiliate_open_api/apis/openapi/v1
서명은 signed-date(yyMMdd'T'HHmmss'Z', GMT) + method + path + query 를 secret key로
HMAC-SHA256 후 hex 인코딩하고, Authorization 헤더에
"CEA algorithm=HmacSHA256, access-key=..., signed-date=..., signature=..." 형태로 싣는다.
COUPANG_PARTNERS_ACCESS_KEY / COUPANG_PARTNERS_SECRET_KEY 필요.

⚠ 쿠팡 파트너스 API 키는 가입 직후가 아니라 파트너스 "최종 승인" 이후에 발급된다.
또한 검색 API는 호출 횟수 제한이 엄격하므로(시간당 호출 수 제한) 키워드를 소량씩
나눠 호출해야 한다. 응답 필드명은 공개 문서/샘플 기준이며 실 키로 검증되지 않았다.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import requests

from flying_geese.config import Settings

logger = logging.getLogger(__name__)

PARTNERS_DOMAIN = "https://api-gateway.coupang.com"
API_PREFIX = "/v2/providers/affiliate_open_api/apis/openapi/v1"
DEEPLINK_PATH = API_PREFIX + "/deeplink"
SEARCH_PATH = API_PREFIX + "/products/search"
COMMISSION_REPORT_PATH = API_PREFIX + "/reports/commission"
MAX_SEARCH_LIMIT = 10


@dataclass(frozen=True)
class AffiliateProduct:
    product_id: str
    product_name: str
    product_price: int
    product_url: str  # 파트너스 추적 링크 (수수료가 붙는 링크)
    product_image: str = ""
    category_name: str = ""
    is_rocket: bool = False
    keyword: str = ""


@dataclass(frozen=True)
class DailyCommission:
    date: str  # yyyyMMdd
    commission: int
    clicks: int = 0
    orders: int = 0
    gmv: int = 0


def sign(secret_key: str, signed_date: str, method: str, path: str, query: str) -> str:
    message = f"{signed_date}{method}{path}{query}"
    return hmac.new(
        secret_key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
    ).hexdigest()


class CoupangPartnersClient:
    def __init__(self, settings: Settings, timeout: float = 10.0):
        self.settings = settings
        self.timeout = timeout

    def _authorization(self, method: str, path: str, query: str) -> str:
        signed_date = time.strftime("%y%m%dT%H%M%SZ", time.gmtime())
        signature = sign(
            self.settings.coupang_partners_secret_key, signed_date, method, path, query
        )
        return (
            "CEA algorithm=HmacSHA256, "
            f"access-key={self.settings.coupang_partners_access_key}, "
            f"signed-date={signed_date}, signature={signature}"
        )

    def _request(self, method: str, path: str, params: dict | None = None, body: dict | None = None) -> dict:
        if not self.settings.coupang_partners_ready():
            raise RuntimeError(
                "COUPANG_PARTNERS_ACCESS_KEY / SECRET_KEY 환경변수가 설정되지 않았습니다. "
                "(파트너스 최종 승인 후 API 키 발급 가능)"
            )
        query = urlencode(params or {})
        headers = {
            "Authorization": self._authorization(method, path, query),
            "Content-Type": "application/json;charset=UTF-8",
        }
        url = PARTNERS_DOMAIN + path + (f"?{query}" if query else "")
        response = requests.request(method, url, json=body, headers=headers, timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()
        if str(payload.get("rCode", "0")) != "0":
            raise RuntimeError(f"쿠팡 파트너스 API 오류: {payload.get('rMessage')}")
        return payload

    def search_products(self, keyword: str, limit: int = 5) -> list[AffiliateProduct]:
        params = {"keyword": keyword, "limit": min(limit, MAX_SEARCH_LIMIT)}
        if self.settings.coupang_partners_sub_id:
            params["subId"] = self.settings.coupang_partners_sub_id
        payload = self._request("GET", SEARCH_PATH, params=params)
        return parse_search_products(payload, keyword)

    def deeplinks(self, coupang_urls: list[str]) -> dict[str, str]:
        """일반 쿠팡 상품 URL → 파트너스 단축 추적 링크 매핑."""
        body: dict = {"coupangUrls": coupang_urls}
        if self.settings.coupang_partners_sub_id:
            body["subId"] = self.settings.coupang_partners_sub_id
        payload = self._request("POST", DEEPLINK_PATH, body=body)
        return parse_deeplinks(payload)

    def commission_report(self, start_date: str, end_date: str) -> list[DailyCommission]:
        """start_date/end_date: yyyyMMdd. 일자별 수수료 실적."""
        payload = self._request(
            "GET", COMMISSION_REPORT_PATH, params={"startDate": start_date, "endDate": end_date}
        )
        return parse_commission_report(payload)


def _to_int(value) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def parse_search_products(payload: dict, keyword: str = "") -> list[AffiliateProduct]:
    """검색 결과를 파싱한다. 상품 하나가 malformed여도 나머지는 그대로 반환한다."""
    data = payload.get("data") or {}
    rows = (data.get("productData") or []) if isinstance(data, dict) else []
    products: list[AffiliateProduct] = []
    for row in rows:
        try:
            if not row.get("productUrl") or not row.get("productName"):
                raise KeyError("productUrl/productName 누락")
            products.append(
                AffiliateProduct(
                    product_id=str(row.get("productId") or ""),
                    product_name=row["productName"].strip(),
                    product_price=_to_int(row.get("productPrice")),
                    product_url=row["productUrl"],
                    product_image=row.get("productImage") or "",
                    category_name=row.get("categoryName") or "",
                    is_rocket=bool(row.get("isRocket")),
                    keyword=row.get("keyword") or keyword,
                )
            )
        except (KeyError, AttributeError, TypeError) as exc:
            logger.warning("malformed 상품 건너뜀: %s (%s)", row, exc)
    return products


def parse_deeplinks(payload: dict) -> dict[str, str]:
    links: dict[str, str] = {}
    for row in payload.get("data") or []:
        original = row.get("originalUrl")
        short = row.get("shortenUrl") or row.get("landingUrl")
        if original and short:
            links[original] = short
    return links


def parse_commission_report(payload: dict) -> list[DailyCommission]:
    rows: list[DailyCommission] = []
    for row in payload.get("data") or []:
        if not row.get("date"):
            logger.warning("날짜 없는 리포트 행 건너뜀: %s", row)
            continue
        rows.append(
            DailyCommission(
                date=str(row["date"]),
                commission=_to_int(row.get("commission")),
                clicks=_to_int(row.get("click")),
                orders=_to_int(row.get("order")),
                gmv=_to_int(row.get("gmv")),
            )
        )
    return rows
