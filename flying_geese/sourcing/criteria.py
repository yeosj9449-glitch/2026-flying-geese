"""큐레이션 입점 기준 평가.

기준 체계 (docs/premium_kids_strategy.md 3장):
  1. 인증 (필수)   - 품목군별 허용 인증 + 인증번호를 직접 조회한 지 90일 이내 + 유효기간 내
  2. 안전성 검사 (필수) - 1년 이내 검사성적서 (농산: 잔류농약 / 수산: 중금속·방사능)
  3. 아이 기준    - 한입 크기·소포장·무첨가가 모두 확인되면 '키즈 전용' 카테고리
  4. 품질 (가점)   - 당도 기록, 수확→출고 2일 이내, 콜드체인
  5. 스토리 (가점) - 농가 사진/인터뷰 제공 가능

1·2를 하나라도 못 넘으면 점수와 무관하게 입점 등급(S/A)이 될 수 없다.
"""
from __future__ import annotations

from datetime import date, timedelta

from flying_geese.models import (
    LeadEvaluation,
    SampleInspection,
    SourcingGrade,
    SourcingStage,
    SupplierLead,
)

ALLOWED_CERTS: dict[str, set[str]] = {
    "과일": {"유기농", "무농약"},
    "농산": {"유기농", "무농약"},
    "수산": {"유기수산물", "무항생제수산물", "활성처리제비사용", "MSC", "ASC"},
    "축산": {"유기축산물", "무항생제", "동물복지"},
}
SAFETY_TEST_LABEL = {
    "과일": "잔류농약",
    "농산": "잔류농약",
    "수산": "중금속·방사능",
    "축산": "항생제 잔류",
}

CERT_REVERIFY_DAYS = 90  # 분기 1회 재조회
CERT_EXPIRY_WARN_DAYS = 30
SAFETY_TEST_VALID_DAYS = 365
SAFETY_TEST_WARN_DAYS = 300
MAX_HARVEST_TO_SHIP_DAYS = 2

_STAGE_ORDER = list(SourcingStage)


_CERT_ALIASES = {
    "유기농산물": "유기농",
    "유기": "유기농",
    "무농약농산물": "무농약",
    "무항생제축산물": "무항생제",
    "동물복지축산농장": "동물복지",
    "활성처리제비사용수산물": "활성처리제비사용",
}


def normalize_cert(cert_type: str) -> str:
    """'유기농산물 인증', 'msc' 같은 표기 변형을 기준 명칭으로 맞춘다."""
    key = cert_type.replace(" ", "").replace("인증", "").upper()
    return _CERT_ALIASES.get(key, key)


def allowed_certs_for(product_type: str) -> set[str]:
    return ALLOWED_CERTS.get(product_type.strip(), ALLOWED_CERTS["농산"])


def evaluate_lead(
    lead: SupplierLead,
    today: date,
    samples: list[SampleInspection] | None = None,
) -> LeadEvaluation:
    missing: list[str] = []
    warnings: list[str] = []
    actions: list[str] = []

    # --- 필수 1: 인증 ---
    cert = normalize_cert(lead.cert_type)
    cert_type_allowed = cert in {normalize_cert(c) for c in allowed_certs_for(lead.product_type)}
    cert_ok = cert_type_allowed
    cert_unknown = not lead.cert_type.strip()
    if not cert_type_allowed:
        missing.append("인증 미확인" if cert_unknown else f"허용되지 않는 인증({lead.cert_type})")
        actions.append(
            f"인증 종류 확인 요청 - {lead.product_type} 허용 인증: "
            + "/".join(sorted(allowed_certs_for(lead.product_type)))
        )
    if cert_type_allowed and not lead.cert_number:
        cert_ok = False
        missing.append("인증번호 미확보")
        actions.append("인증번호 요청")
    if cert_type_allowed and lead.cert_number:
        if lead.cert_verified_on is None:
            cert_ok = False
            missing.append("인증번호 직접 조회 안 함")
            actions.append("친환경인증관리정보시스템(enviagro.go.kr)에서 인증번호·유효기간 조회")
        elif (today - lead.cert_verified_on).days > CERT_REVERIFY_DAYS:
            cert_ok = False
            missing.append(f"인증 조회 {CERT_REVERIFY_DAYS}일 경과")
            actions.append("인증 재조회 (분기 1회)")
    if lead.cert_expiry is not None:
        if lead.cert_expiry < today:
            cert_ok = False
            missing.append("인증 유효기간 만료")
            actions.append("갱신된 인증서 요청")
        elif lead.cert_expiry <= today + timedelta(days=CERT_EXPIRY_WARN_DAYS):
            warnings.append(f"인증 만료 임박({lead.cert_expiry.isoformat()})")
            actions.append("갱신 인증서 수령 후 재조회")

    # --- 필수 2: 안전성 검사 ---
    test_label = SAFETY_TEST_LABEL.get(lead.product_type.strip(), "잔류농약")
    safety_ok = False
    if lead.safety_test_on is None:
        missing.append(f"{test_label} 검사성적서 없음")
        actions.append(f"최근 1년 이내 {test_label} 검사성적서 요청")
    else:
        age = (today - lead.safety_test_on).days
        if age > SAFETY_TEST_VALID_DAYS:
            missing.append(f"{test_label} 검사 1년 경과")
            actions.append(f"신규 {test_label} 검사성적서 요청")
        else:
            safety_ok = True
            if age > SAFETY_TEST_WARN_DAYS:
                warnings.append("검사성적서 갱신 시기 도래")

    # --- 3: 아이 기준 ---
    kid_checks = {
        "한입 크기(소과) 선별": lead.kid_bite_size,
        "1kg 이하 소포장": lead.kid_small_pack,
        "무첨가·무염": lead.kid_no_additive,
    }
    kids_ok = all(kid_checks.values())
    for label, ok in kid_checks.items():
        if not ok:
            actions.append(f"{label} 가능 여부 문의")

    # --- 점수 ---
    mandatory_ok = cert_ok and safety_ok
    if mandatory_ok:
        score = 60
    elif cert_type_allowed:
        score = 30
    else:
        score = 0
    score += 8 * sum(kid_checks.values())
    if lead.brix is not None:
        score += 3
    if lead.harvest_to_ship_days is not None and lead.harvest_to_ship_days <= MAX_HARVEST_TO_SHIP_DAYS:
        score += 4
    if lead.cold_chain:
        score += 3
    if lead.story_available:
        score += 6
    else:
        actions.append("농가 사진·인터뷰(스토리 콘텐츠) 제공 요청")
    if lead.product_type.strip() in {"수산", "축산"} and not lead.cold_chain:
        warnings.append("수산/축산인데 콜드체인 미확인")

    if mandatory_ok and kids_ok:
        grade = SourcingGrade.KIDS
    elif mandatory_ok:
        grade = SourcingGrade.PASS
    elif cert_type_allowed or cert_unknown:
        # 인증 정보를 아직 못 받은 발굴 단계 리드는 '불가'가 아니라 '확인 필요'
        grade = SourcingGrade.FIXABLE
    else:
        grade = SourcingGrade.REJECT

    # --- 샘플 검수 & 파이프라인 정합성 ---
    lead_samples = [s for s in (samples or []) if s.lead_id == lead.lead_id]
    sample_results = [s.passed for s in lead_samples if s.passed is not None]
    sample_passed = (all(sample_results) if sample_results else None)

    stage_idx = _STAGE_ORDER.index(lead.stage)
    if grade in (SourcingGrade.KIDS, SourcingGrade.PASS) and stage_idx < _STAGE_ORDER.index(
        SourcingStage.SAMPLE_REQUESTED
    ):
        actions.insert(0, "샘플 주문 (직접 수령해서 검수)")
    if grade in (SourcingGrade.KIDS, SourcingGrade.PASS) and sample_passed and lead.stage == SourcingStage.SAMPLE_REVIEW:
        actions.insert(0, "입점 확정 → 상세페이지(인증번호·검사성적서·산지 스토리) 제작 착수")
    if sample_passed is False and lead.stage in (SourcingStage.SAMPLE_REVIEW, SourcingStage.SAMPLE_REQUESTED):
        actions.insert(0, "샘플 불합격 - 재샘플 또는 보류/탈락 결정")
    if grade == SourcingGrade.REJECT and lead.stage != SourcingStage.ONBOARDED:
        actions.insert(0, "탈락 처리 검토 (허용 인증 보유 농가로 대체 탐색)")
    if lead.stage == SourcingStage.ONBOARDED:
        if grade not in (SourcingGrade.KIDS, SourcingGrade.PASS):
            warnings.append("필수 기준 미충족 상태로 입점됨 - 판매 중지 검토")
        if sample_passed is not True:
            warnings.append("샘플 검수 통과 기록 없이 입점됨")
    if sample_passed is False:
        warnings.append("샘플 검수 불합격 이력")
    if lead.next_action_date and lead.next_action_date < today and lead.stage not in (
        SourcingStage.DROPPED,
        SourcingStage.ON_HOLD,
    ):
        warnings.append(f"후속조치 지연({lead.next_action_date.isoformat()})")

    if lead.stage == SourcingStage.DROPPED:
        actions = []
    elif lead.stage == SourcingStage.ONBOARDED:
        # 입점 완료 건은 문의성 액션 대신 인증/검사 유지관리 액션만 남긴다.
        actions = [a for a in actions if "재조회" in a or "갱신" in a or "검사성적서" in a]

    return LeadEvaluation(
        lead=lead,
        grade=grade,
        score=min(score, 100),
        cert_ok=cert_ok,
        safety_ok=safety_ok,
        kids_ok=kids_ok,
        missing=missing,
        warnings=warnings,
        suggested_actions=actions,
        sample_passed=sample_passed,
    )


def evaluate_leads(
    leads: list[SupplierLead], today: date, samples: list[SampleInspection] | None = None
) -> list[LeadEvaluation]:
    """등급(S→X) → 점수 내림차순으로 정렬한 평가 결과."""
    grade_rank = {grade: idx for idx, grade in enumerate(SourcingGrade)}
    evaluations = [evaluate_lead(lead, today, samples) for lead in leads]
    return sorted(evaluations, key=lambda e: (grade_rank[e.grade], -e.score, e.lead.lead_id))
