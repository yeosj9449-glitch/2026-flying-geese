# 농수산물 위탁판매 상품 선정 및 운영 자동화 시스템

무자본/소자본 기반 블루오션 품목을 자동 소싱하고, 발주·배송까지 이어지는
5단계 파이프라인을 모듈화한 Python 3.10+ 시스템입니다.

- 목표: 월 매출 500만 원 (순수익 약 75~100만 원)
- 개발 환경: Claude Code, Python 3.10+

## 5단계 구조

| 단계 | 모듈 | 내용 |
| --- | --- | --- |
| 1 | `flying_geese/stage1_calendar` | 12개월 제철 캘린더(대표품목→세부품종, 제철 구간) 매칭, KAMIS 도소매가 API 연동, 전월/전년 대비 폭등 품목(기본 20%↑) 자동 제외, 스마트 APC 우수 출하 품목 연동, 다음 달 제철 예정 미리보기 |
| 2 | `flying_geese/stage2_blue_ocean` | 네이버 데이터랩/검색광고 API, 대표 품목 → 세부 품종 확장, 블루오션 지수(검색량/경쟁상품 수) × 검색 모멘텀 스코어링 |
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

### 블루오션 스코어링 업그레이드: 검색 모멘텀 반영 + 데이터 누락 안전장치

- **검색 모멘텀**: 블루오션 지수(검색량/경쟁상품 수)는 특정 시점의 스냅샷이라, 이미
  인기가 식고 있는 키워드도 경쟁만 적으면 높은 점수를 받는 문제가 있었습니다.
  `data/sample/search_trends.json`(네이버 데이터랩 `search_trend`/`latest_ratio_by_keyword`
  결과로 채우는 값, 1.0=변화없음·1.0 초과=상승세)을 블루오션 지수에 곱해
  `trending_score`를 최종 순위 기준으로 사용합니다 — 원시 지수가 더 낮아도 상승세인
  품종이 앞설 수 있습니다 (`VarietyCandidate.trending_score`, 0.5~2.0배로 clamp).
- **경쟁상품 데이터 누락 안전장치**: 기존에는 경쟁상품 수 데이터가 없는 품종을
  `0`으로 임의 대체해, 데이터가 없을 뿐인데 블루오션 지수가 검색량 그대로 튀어올라
  1위로 오인될 위험이 있었습니다. 이제는 그런 품종을 스코어링에서 제외하고
  `PipelineReport.blue_ocean_missing_competitor_data`로 별도 보고합니다(CLI에도
  `⚠ 경쟁상품 데이터 없음` 경고로 출력).
- `MIN_BLUE_OCEAN_SEARCH_VOLUME` 환경변수로 노이즈 필터링 최소 검색량을 조정할 수
  있습니다(기본 100, 다른 비즈니스 규칙 파라미터와 동일하게 `.env`로 관리).

### 4단계 업그레이드: 플랫폼 판매 수수료 반영 (⚠ 순수익 목표 재검토 필요)

기존에는 `expected_net_profit`(순수익)이 `expected_gross_margin`(총마진)과 완전히
같은 값이었습니다 — 마진율(15%/18%)만 반영하고, 실제로 매출에서 차감되는 플랫폼
판매 수수료가 전혀 빠지지 않은 상태였습니다. `PLATFORM_COMMISSION_RATE`(기본
10%, 스마트스토어/쿠팡 등 위탁판매 채널의 일반적인 수수료율을 참고한 기본값이며
실제 채널에 맞게 `.env`에서 조정 필요)를 매출 기준으로 차감하도록 수정했습니다.

**이 수정으로 드러난 점**: 기본 믹스(상시 15% / 프리미엄 18% 마진, 월 500만원
목표) 기준으로 총마진은 817,920원이지만, 10% 수수료를 반영하면 순수익은
**318,720원**으로 떨어집니다 — 마스터 기획서의 목표 순수익(75~100만 원)에
크게 못 미칩니다. 목표를 달성하려면 다음 중 하나(또는 조합)가 필요합니다:
목표 매출 상향, 마진율 상향(예: 자사몰 직거래 비중 확대로 수수료 자체를 회피),
또는 실제 채널의 수수료율이 10%보다 낮다면 `PLATFORM_COMMISSION_RATE`를
현실화. `flying_geese/cli.py` 실행 시 총마진/수수료/순수익이 각각 표시됩니다.

### 3단계 업그레이드: 제외 공급처가 신뢰점수만으로 상위 노출되던 문제 수정

기존에는 통과 여부와 무관하게 `trust_score` 하나만으로 공급처를 정렬했습니다.
그 결과 배송시간만 근소하게 기준을 초과해 제외된 공급처가, 다른 지표(이행률·
반품률)가 우수하다는 이유로 통과 공급처보다 위에 노출될 수 있었습니다 —
"CS 위험 공급처 자동 배제" 취지와 맞지 않는 표시 순서였습니다. 이제 통과 여부를
1차 정렬 기준으로 두어, 제외된 공급처는 점수와 무관하게 항상 통과 공급처 아래에
표시됩니다.

### 5단계 업그레이드: 발송 처리 중복 호출 방지 (멱등성)

기존 `dispatch_orders`는 주문의 현재 상태를 확인하지 않고 송장번호가 있으면
바로 발송 API를 호출했습니다. 송장 CSV를 매일 누적/재업로드하는 운영 방식에서는
이미 발송 처리된 주문이 다시 포함될 수 있는데, 이 경우 발송 API가 중복
호출되어 고객에게 중복 발송 알림이 갈 위험이 있었습니다. 이제 `OrderStatus.NEW`
상태인 주문만 처리하고, 이미 발송/취소된 주문은 조용히 건너뜁니다(재처리도,
"미수집" 목록에도 포함되지 않음).

### 실 API 연동 안정성 수정: JSON null 필드로 인한 파싱 크래시 방지

`KamisClient._parse`와 `NaverDatalabClient.latest_ratio_by_keyword`가
`dict.get(key, default)`만으로 결측값을 처리하고 있었는데, 이 패턴은 키가
아예 없을 때만 default를 적용합니다. KAMIS/네이버 데이터랩처럼 일부 필드를
JSON `null`로 내려주는 API에서는 값이 `None`인 채로 넘어와 `.strip()`이나
`float()` 호출에서 크래시가 나고, 응답 전체(다른 정상 품목까지 포함)의 파싱이
중단될 위험이 있었습니다. `value or default` 폴백으로 교체해 결측 필드가 있는
행만 안전하게 기본값 처리되도록 수정했고, 두 모듈 모두 네트워크 없이 검증
가능한 순수 파싱 로직 단위 테스트를 새로 추가했습니다(기존에는 테스트가
전혀 없었습니다).

같은 이유로 `RestCommerceClient.fetch_new_orders`도 수정했습니다 - 기존에는
`[_parse_order(row) for row in ...]` 형태라 주문 하나(예: 수량이 null)가
malformed이면 그 배치 전체가 예외로 죽어, **그날 들어온 다른 정상 주문까지
전부 발주서/배송 처리로 못 넘어가는** 더 심각한 실패였습니다(단순 시세 데이터가
아니라 실제 고객 주문이라 영향이 큽니다). `_parse_orders`로 분리해 malformed
주문 한 건만 로그를 남기고 건너뛰도록 수정, 순수 파싱 로직 단위 테스트를
추가했습니다.

### 신규 추가: aT 온라인도매시장(KAFB2B) 클라이언트

마스터 기획서 1단계에 명시된 "aT 온라인도매시장(KAFB2B)" 연동은 `Settings`에
`AT_KAFB2B_API_KEY`/`AT_KAFB2B_BASE_URL`이 이미 정의돼 있었는데도 정작 이를
사용하는 클라이언트 모듈이 없었습니다(KAMIS는 있는데 KAFB2B만 빠진 상태).
`flying_geese/stage1_calendar/at_kafb2b_client.py`를 추가했습니다. KAFB2B는
KAMIS와 달리 널리 공개된 표준 스펙이 없고 이용기관별 계약을 통해 API 문서를
받는 구조라, 엔드포인트/파라미터명은 참고용 기본값이며 실제 연동 시 계약된
스펙에 맞게 조정이 필요합니다 — 다만 KamisClient/commerce_api.py 수정에서
확인한 "행 하나의 결측 필드가 배치 전체를 죽이면 안 된다"는 안전장치는 처음부터
반영해뒀습니다.

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

## API 키 발급 전: 수동 리서치로 상품 선정만 먼저 실행

KAMIS/네이버 API 키를 아직 발급받지 못했어도, 1~2단계("상품 선정" - 제철
검증 + 가격 변동성 필터 + 블루오션 스코어링)만큼은 운영자가 직접 조사한 실제
숫자로 실행할 수 있습니다. KAMIS(www.kamis.or.kr)와 네이버 검색광고/데이터랩
관리시스템은 로그인만 하면 **API 키 없이 화면에서 직접 조회**가 가능하므로,
그 값을 그대로 입력하면 됩니다. 3~5단계(공급처 필터, 마진 시뮬레이터, 발송
자동화)는 공급처 데이터/커머스 API가 필요해 포함되지 않습니다.

```bash
cp data/manual/price_records.example.json data/manual/price_records.json
# search_volumes.json / competitor_counts.json / search_trends.json은 선택 -
# 없으면 해당 정보 없이 안전하게 진행됩니다(블루오션 스코어링만 비어있게 됨).
python -m flying_geese.cli select
```

- `data/manual/price_records.json`: KAMIS에서 조회한 대표 품목의 최근가/약 30일 전/약 365일 전 가격 3개 시점 (`product_code`는 실제 KAMIS 코드가 아니어도 되고, 같은 품목끼리 묶이도록 `product_name`과 동일하게 쓰면 됩니다) - **필수**
- `data/manual/search_volumes.json`: 네이버 검색광고 키워드 도구에서 조회한 세부 품종별 월간 검색량 - 없으면 해당 품종은 블루오션 후보에서 빠집니다
- `data/manual/competitor_counts.json`: 쿠팡/스마트스토어에서 직접 검색해 눈으로 센 등록 상품 수 - 없으면 "데이터 누락"으로 보고되고 스코어링에서 제외됩니다
- `data/manual/search_trends.json`: 네이버 데이터랩에서 비교한 검색 모멘텀 (선택, 없으면 중립값 1.0)

제철 캘린더/품종 매핑은 `data/sample/seasonal_calendar.json`, `variety_map.json`
(데모용 가짜 데이터가 아니라 실제 참고 데이터)을 그대로 재사용합니다.
`data/manual/*.json`(예시 파일 제외)은 `.gitignore` 처리돼 커밋되지 않습니다.

## 실전 파이프라인 (실 API 연동)

`flying_geese/live_pipeline.py`의 `run_live_pipeline()` (또는
`python -m flying_geese.cli run-live`)이 `data/sample/` 대신 실제 API를 호출해
같은 5단계를 수행합니다. 데모 파이프라인이 이미 검증한 순수 로직(가격 변동성
판정, 블루오션 스코어링, 공급처 리스크 필터, 마진 시뮬레이터, 발송 처리)을
그대로 재사용하고, **데이터를 어디서 가져오는지만** 다릅니다.

⚠ **이 저장소의 자동화 테스트는 실 API에 대한 네트워크 호출 자체를 검증하지
못했습니다** (오프라인 샌드박스 환경). 각 클라이언트의 응답 파싱 로직과
오케스트레이션 흐름은 모킹으로 검증했지만, 실제 KAMIS/aT/네이버/커머스
API가 문서와 정확히 같은 형태로 응답하는지는 실 키로 직접 확인해야 합니다.

### 설정 절차

1. `.env.example`을 `.env`로 복사하고 아래 값을 채웁니다.
   - `KAMIS_CERT_KEY` / `KAMIS_CERT_ID`: KAMIS 오픈API (`stage1_calendar/kamis_client.py`) - 필수
   - `NAVER_SEARCHAD_API_KEY` / `SECRET_KEY` / `CUSTOMER_ID`: 네이버 검색광고 연관키워드 (`stage2_blue_ocean/naver_searchad.py`) - 필수 (블루오션 스코어링의 검색량 산정에 반드시 필요)
   - `AT_KAFB2B_API_KEY` / `AT_KAFB2B_BASE_URL`: aT 온라인도매시장 경락가 (`stage1_calendar/at_kafb2b_client.py`) - 선택, 미설정 시 KAMIS만 사용
   - `NAVER_DATALAB_CLIENT_ID` / `SECRET`: 네이버 데이터랩 검색어트렌드 (`stage2_blue_ocean/naver_datalab.py`) - 선택, 미설정 시 검색 모멘텀은 중립값(1.0)으로 처리
   - `COMMERCE_API_BASE_URL` / `COMMERCE_API_KEY`: 자사몰/커머스 플랫폼 주문 연동 (`stage5_automation/commerce_api.py`) - 필수
2. `data/live/kamis_item_map.example.json`을 `data/live/kamis_item_map.json`으로
   복사하고, 취급할 대표 품목별 KAMIS `item_code`/`kind_code`/`category_code`를
   **KAMIS 표준코드 조회 API 또는 공식 문서에서 직접 확인**해 채웁니다
   (`TODO_...` placeholder가 남아있으면 실행 시 명확한 에러로 막습니다).
3. 아래는 공식 실시간 API가 없어 데모와 마찬가지로 운영자가 직접 관리하는
   로컬 데이터입니다. `data/live/*.example.json`을 복사해 채웁니다(파일이
   아예 없어도 안전한 기본값으로 동작하도록 만들었습니다 - 아래 참고).
   - `apc_sites.json`: 실제 조사한 스마트 APC 정보 (없으면 우선 연동 표시 없이 진행)
   - `competitor_counts.json`: 쿠팡/스마트스토어 등록 상품 수 (없으면 미등록 품종을 "경쟁 심함"으로 보수적으로 가정)
   - `suppliers.json`: 실제 공급처 이행률/배송시간/반품률 (필수 - 없으면 3단계가 실행되지 않음)
   - `tracking.csv`: 농가에서 회신한 송장번호 (`order_id,tracking_number`)
4. `python -m flying_geese.cli run-live` 실행. `data/sample/seasonal_calendar.json`,
   `variety_map.json`은 데모용으로 지어낸 가짜 데이터가 아니라 실제 농산물
   품종/제철 지식으로 작성한 참고 데이터라 그대로 재사용하며, 취급 품목
   범위에 맞게 계속 보강하는 것을 권장합니다 (반대로 `apc_sites.json` 등
   `data/sample/`의 나머지 파일은 데모용 예시라 실전에서 절대 그대로 쓰면
   안 됩니다 - `data/live/`에 실제 값을 채워야 합니다).

`data/live/*.json`, `*.csv`(예시 파일 제외)는 운영자별 민감 정보라 `.gitignore`
에 등록돼 있어 커밋되지 않습니다.

## 디렉터리 구조

```
flying_geese/
  config.py            # 환경변수 기반 설정
  models.py             # 단계 공용 데이터 모델
  pipeline.py            # 데모 5단계 오케스트레이터 (data/sample 사용)
  live_pipeline.py        # 실전 5단계 오케스트레이터 (실 API 연동)
  product_selection.py    # API 키 없이 1~2단계(상품 선정)만 실행 (data/manual 사용)
  cli.py                 # python -m flying_geese.cli run | run-live | select
  stage1_calendar/        # 제철 캘린더, KAMIS/aT KAFB2B, 가격 변동성, APC 연동
  stage2_blue_ocean/      # 네이버 데이터랩/검색광고, 품종 확장, 블루오션 스코어링
  stage3_supplier/        # 공급처 신뢰 점수, CS 리스크 필터
  stage4_simulator/       # 마진 시뮬레이터, 현금흐름
  stage5_automation/      # 주문 수집, 발주서 엑셀, 배송 처리
data/sample/             # 데모/테스트용 샘플 데이터
data/live/               # 실전 파이프라인용 로컬 설정 (.example.json/csv만 버전관리)
data/manual/             # 수동 리서치 상품 선정용 로컬 설정 (.example.json만 버전관리)
tests/                    # pytest 단위/통합 테스트
```
