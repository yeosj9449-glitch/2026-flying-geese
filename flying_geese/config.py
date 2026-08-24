"""환경 변수 기반 시스템 설정.

모든 외부 API 키/시크릿은 코드에 하드코딩하지 않고 환경 변수(.env)로 주입한다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def _env_float(key: str, default: float) -> float:
    raw = os.getenv(key)
    return float(raw) if raw else default


def _env_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    return int(raw) if raw else default


@dataclass(frozen=True)
class Settings:
    # --- 1단계: KAMIS / aT 도매가 ---
    kamis_cert_key: str = field(default_factory=lambda: _env("KAMIS_CERT_KEY"))
    kamis_cert_id: str = field(default_factory=lambda: _env("KAMIS_CERT_ID"))
    kamis_base_url: str = field(
        default_factory=lambda: _env(
            "KAMIS_BASE_URL", "https://www.kamis.or.kr/service/price/xml.do"
        )
    )
    at_kafb2b_api_key: str = field(default_factory=lambda: _env("AT_KAFB2B_API_KEY"))
    at_kafb2b_base_url: str = field(
        default_factory=lambda: _env("AT_KAFB2B_BASE_URL", "")
    )

    # --- 2단계: 네이버 데이터랩 / 검색광고 ---
    naver_datalab_client_id: str = field(
        default_factory=lambda: _env("NAVER_DATALAB_CLIENT_ID")
    )
    naver_datalab_client_secret: str = field(
        default_factory=lambda: _env("NAVER_DATALAB_CLIENT_SECRET")
    )
    naver_searchad_api_key: str = field(
        default_factory=lambda: _env("NAVER_SEARCHAD_API_KEY")
    )
    naver_searchad_secret_key: str = field(
        default_factory=lambda: _env("NAVER_SEARCHAD_SECRET_KEY")
    )
    naver_searchad_customer_id: str = field(
        default_factory=lambda: _env("NAVER_SEARCHAD_CUSTOMER_ID")
    )

    # --- 5단계: 자사몰/커머스 API ---
    commerce_api_base_url: str = field(
        default_factory=lambda: _env("COMMERCE_API_BASE_URL")
    )
    commerce_api_key: str = field(default_factory=lambda: _env("COMMERCE_API_KEY"))

    # --- 비즈니스 규칙 파라미터 ---
    price_surge_exclude_pct: float = field(
        default_factory=lambda: _env_float("PRICE_SURGE_EXCLUDE_PCT", 20.0)
    )
    min_supplier_fulfillment_rate: float = field(
        default_factory=lambda: _env_float("MIN_SUPPLIER_FULFILLMENT_RATE", 0.95)
    )
    max_supplier_return_rate: float = field(
        default_factory=lambda: _env_float("MAX_SUPPLIER_RETURN_RATE", 0.03)
    )
    max_supplier_avg_delivery_hours: float = field(
        default_factory=lambda: _env_float("MAX_SUPPLIER_AVG_DELIVERY_HOURS", 30.0)
    )
    target_monthly_revenue: int = field(
        default_factory=lambda: _env_int("TARGET_MONTHLY_REVENUE", 5_000_000)
    )

    def kamis_ready(self) -> bool:
        return bool(self.kamis_cert_key and self.kamis_cert_id)

    def naver_datalab_ready(self) -> bool:
        return bool(self.naver_datalab_client_id and self.naver_datalab_client_secret)

    def naver_searchad_ready(self) -> bool:
        return bool(
            self.naver_searchad_api_key
            and self.naver_searchad_secret_key
            and self.naver_searchad_customer_id
        )


def load_settings() -> Settings:
    """환경 변수를 읽어 Settings 인스턴스를 생성한다."""
    return Settings()
