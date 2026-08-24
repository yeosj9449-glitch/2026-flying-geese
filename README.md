# 농수산물 위탁판매 상품 선정 및 운영 자동화 시스템

무자본/소자본 기반 블루오션 품목을 자동 소싱하고, 발주·배송까지 이어지는
5단계 파이프라인을 모듈화한 Python 3.10+ 시스템입니다.

- 목표: 월 매출 500만 원 (순수익 약 75~100만 원)
- 개발 환경: Claude Code, Python 3.10+

## 5단계 구조

| 단계 | 모듈 | 내용 |
| --- | --- | --- |
| 1 | `flying_geese/stage1_calendar` | 12개월 제철 캘린더(대표품목→세부품종, 제철 구간) 매칭, KAMIS 도소매가 API 연동, 전월/전년 대비 폭등 품목(기본 20%↑) 자동 제외, 스마트 APC 우수 출하 품목 연동, 다음 달 제철 예정 미리보기 |
| 2 | `flying_geese/stage2_blue_ocean` | 네이버 데이터랩/검색광고 API, 대표 품목 → 세부 품종 확장, 블루오션 지수(검색량/경쟁상품 수) 스코어링 |
| 3 | `flying_geese/stage3_supplier` | 공급처 이행률/배송시간/반품률 기반 신뢰 점수 산출 및 CS 위험 공급처 자동 배제 |
| 4 | `flying_geese/stage4_simulator` | 상시 제철품목 vs 프리미엄 선물세트 믹스로 목표 매출 역산, 정산 주기 기반 운전자금 시뮬레이션 |
| 5 | `flying_geese/stage5_automation` | 신규 주문 수집 → 공급처별 발주서 엑셀 자동 생성 → 송장 수집 → 발송 처리 API 호출 및 배송 상태 모니터링 |

`flying_geese/pipeline.py`가 5단계를 순서대로 오케스트레이션합니다.

### 제철 캘린더 게이팅 (2단계 스코어링과 연동)

1단계에서 통과한(폭등 제외 + 가격 안정) 대표 품목 중, `data/sample/seasonal_calendar.json`의
이번 달 제철 구간(`peak_months`)에 매칭되는 세부 품종만 2단계 블루오션 스코어링 대상이
됩니다. 예를 들어 8월에는 사과 카테고리에서 `감홍사과`/`부사사과`가 아니라 제철인
`홍로사과`만 채점됩니다 — 비수기 품종을 추천 상단에 노출하는 것을 방지합니다.
제철 캘린더에 없는 대표 품목은 기존 품종 매핑표(`variety_map.json`) 전체를 훑는
방식으로 자동 폴백합니다. 또한 다음 달에 새로 제철이 시작되는 품종은
`upcoming_next_month`로 미리 확인할 수 있어(이미 이번 달도 제철인 품종은 제외),
사전예약/입고 준비 마케팅에 활용할 수 있습니다.

`run_demo_pipeline(target_month=...)`로 기준월을 지정할 수 있고, 생략하면 실행 시점의
달력월을 사용합니다. `flying_geese/stage1_calendar/seasonal_calendar.py`가 로딩/조회
로직을 담당합니다.

## 빠른 시작 (API 키 없이 샘플 데이터로 전체 흐름 검증)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python -m flying_geese.cli run
```

`data/sample/`의 로컬 데이터로 1~5단계를 모두 실행하며, 발주서 엑셀은
`output/purchase_order.xlsx`에 생성됩니다.

## 테스트

```bash
pytest
```

가격 변동성 필터, 블루오션 스코어링, 공급처 리스크 필터, 마진/현금흐름
시뮬레이터, 발주서 엑셀 생성, 배송 처리, 전체 파이프라인 통합까지 포함합니다.

## 실 서비스 연동

`.env.example`을 `.env`로 복사한 뒤 아래 값을 채우면 각 클라이언트가 실 API를 호출합니다.

- `KAMIS_CERT_KEY` / `KAMIS_CERT_ID`: KAMIS 오픈API (`stage1_calendar/kamis_client.py`)
- `NAVER_DATALAB_CLIENT_ID` / `SECRET`: 네이버 데이터랩 검색어트렌드 (`stage2_blue_ocean/naver_datalab.py`)
- `NAVER_SEARCHAD_API_KEY` / `SECRET_KEY` / `CUSTOMER_ID`: 네이버 검색광고 연관키워드 (`stage2_blue_ocean/naver_searchad.py`)
- `COMMERCE_API_BASE_URL` / `COMMERCE_API_KEY`: 자사몰/커머스 플랫폼 주문 연동 (`stage5_automation/commerce_api.py`)

공영도매시장 경락가(aT KAFB2B), 쿠팡/스마트스토어 경쟁 상품 수는 공식 오픈API가
없거나 계약이 필요하므로, `MarketplaceRankSource` / APC 로더처럼 어댑터를
갈아끼울 수 있는 인터페이스로 설계했습니다. 운영자가 수집한 데이터를
`data/` 하위 JSON/CSV로 채우거나, 자체 크롤러를 어댑터로 연결하면 됩니다.

## 디렉터리 구조

```
flying_geese/
  config.py            # 환경변수 기반 설정
  models.py             # 단계 공용 데이터 모델
  pipeline.py            # 5단계 오케스트레이터 (데모: data/sample 사용)
  cli.py                 # python -m flying_geese.cli run
  stage1_calendar/        # 제철 캘린더, KAMIS/aT, 가격 변동성, APC 연동
  stage2_blue_ocean/      # 네이버 데이터랩/검색광고, 품종 확장, 블루오션 스코어링
  stage3_supplier/        # 공급처 신뢰 점수, CS 리스크 필터
  stage4_simulator/       # 마진 시뮬레이터, 현금흐름
  stage5_automation/      # 주문 수집, 발주서 엑셀, 배송 처리
data/sample/             # 데모/테스트용 샘플 데이터
tests/                    # pytest 단위/통합 테스트
```
