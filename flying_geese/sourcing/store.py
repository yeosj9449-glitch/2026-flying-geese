"""소싱 관리 데이터 저장소 (CSV - 엑셀/구글시트에서 그대로 열고 편집).

data/sourcing/
  leads.csv     공급처 마스터 (1행 = 1공급처)
  contacts.csv  컨택 이력 (누적, 1행 = 1회 연락)
  samples.csv   샘플 검수 기록 (누적)
  history.csv   대시보드 생성 시점의 퍼널 스냅샷 (자동 누적)

실제 파일에는 농가 연락처 등 개인정보가 들어가므로 .gitignore 처리하고,
*.example.csv 템플릿만 버전관리한다. 실제 파일이 없으면 예시 파일로 동작한다.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from flying_geese.models import (
    ContactLog,
    LeadEvaluation,
    SampleInspection,
    SourcingGrade,
    SourcingStage,
    SupplierLead,
)
from flying_geese.tabular import (
    parse_bool,
    parse_date,
    parse_float,
    parse_int,
    pick,
    read_csv_rows,
    split_list,
    write_csv_rows,
)

DEFAULT_SOURCING_DIR = Path(__file__).resolve().parents[2] / "data" / "sourcing"

LEAD_HEADERS = [
    "ID", "공급처명", "품목군", "취급품목", "지역", "발굴경로", "담당자", "연락처", "이메일", "단계",
    "인증종류", "인증번호", "인증유효기간", "인증조회일", "검사종류", "검사일",
    "한입크기", "소포장", "무첨가", "당도Brix", "수확출고일수", "콜드체인", "스토리",
    "다음액션", "다음액션일", "메모",
]
CONTACT_HEADERS = ["ID", "일자", "채널", "내용", "결과"]
SAMPLE_HEADERS = ["ID", "품목", "수령일", "배송일수", "당도Brix", "신선도", "맛", "포장", "아이적합", "메모"]
HISTORY_HEADERS = ["일자"] + [s.value for s in SourcingStage] + [g.value for g in SourcingGrade]


def resolve(directory: Path, name: str) -> tuple[Path, bool]:
    """실제 파일이 있으면 그것을, 없으면 *.example.csv를 돌려준다. (경로, 예시여부)"""
    real = directory / f"{name}.csv"
    if real.exists():
        return real, False
    return directory / f"{name}.example.csv", True


def parse_stage(value: str) -> SourcingStage:
    text = (value or "").strip()
    for stage in SourcingStage:
        if stage.value == text:
            return stage
    return SourcingStage.DISCOVERED


def lead_from_row(row: dict[str, str]) -> SupplierLead:
    return SupplierLead(
        lead_id=pick(row, "ID", "id"),
        supplier_name=pick(row, "공급처명", "농가명"),
        product_type=pick(row, "품목군") or "농산",
        items=split_list(pick(row, "취급품목", "품목")),
        region=pick(row, "지역"),
        source_channel=pick(row, "발굴경로"),
        contact_name=pick(row, "담당자"),
        phone=pick(row, "연락처", "전화"),
        email=pick(row, "이메일"),
        stage=parse_stage(pick(row, "단계")),
        cert_type=pick(row, "인증종류"),
        cert_number=pick(row, "인증번호"),
        cert_expiry=parse_date(pick(row, "인증유효기간")),
        cert_verified_on=parse_date(pick(row, "인증조회일")),
        safety_test_type=pick(row, "검사종류"),
        safety_test_on=parse_date(pick(row, "검사일")),
        kid_bite_size=parse_bool(pick(row, "한입크기")),
        kid_small_pack=parse_bool(pick(row, "소포장")),
        kid_no_additive=parse_bool(pick(row, "무첨가")),
        brix=parse_float(pick(row, "당도Brix", "당도")),
        harvest_to_ship_days=parse_int(pick(row, "수확출고일수")),
        cold_chain=parse_bool(pick(row, "콜드체인")),
        story_available=parse_bool(pick(row, "스토리")),
        next_action=pick(row, "다음액션"),
        next_action_date=parse_date(pick(row, "다음액션일")),
        notes=pick(row, "메모"),
    )


def lead_to_row(lead: SupplierLead) -> dict:
    return {
        "ID": lead.lead_id, "공급처명": lead.supplier_name, "품목군": lead.product_type,
        "취급품목": ", ".join(lead.items), "지역": lead.region, "발굴경로": lead.source_channel,
        "담당자": lead.contact_name, "연락처": lead.phone, "이메일": lead.email, "단계": lead.stage.value,
        "인증종류": lead.cert_type, "인증번호": lead.cert_number, "인증유효기간": lead.cert_expiry,
        "인증조회일": lead.cert_verified_on, "검사종류": lead.safety_test_type, "검사일": lead.safety_test_on,
        "한입크기": lead.kid_bite_size, "소포장": lead.kid_small_pack, "무첨가": lead.kid_no_additive,
        "당도Brix": lead.brix, "수확출고일수": lead.harvest_to_ship_days, "콜드체인": lead.cold_chain,
        "스토리": lead.story_available, "다음액션": lead.next_action, "다음액션일": lead.next_action_date,
        "메모": lead.notes,
    }


def load_leads(path: Path) -> list[SupplierLead]:
    return [lead_from_row(row) for row in read_csv_rows(path) if pick(row, "ID", "id")]


def load_contacts(path: Path) -> list[ContactLog]:
    if not path.exists():
        return []
    return [
        ContactLog(
            lead_id=pick(row, "ID"),
            contacted_on=parse_date(pick(row, "일자")),
            channel=pick(row, "채널"),
            summary=pick(row, "내용"),
            outcome=pick(row, "결과"),
        )
        for row in read_csv_rows(path)
        if pick(row, "ID")
    ]


def load_samples(path: Path) -> list[SampleInspection]:
    if not path.exists():
        return []
    return [
        SampleInspection(
            lead_id=pick(row, "ID"),
            item=pick(row, "품목"),
            received_on=parse_date(pick(row, "수령일")),
            shipping_days=parse_int(pick(row, "배송일수")),
            brix=parse_float(pick(row, "당도Brix", "당도")),
            freshness_score=parse_int(pick(row, "신선도")),
            taste_score=parse_int(pick(row, "맛")),
            packaging_score=parse_int(pick(row, "포장")),
            kid_fit_score=parse_int(pick(row, "아이적합")),
            notes=pick(row, "메모"),
        )
        for row in read_csv_rows(path)
        if pick(row, "ID")
    ]


def append_contact(path: Path, log: ContactLog) -> Path:
    rows = read_csv_rows(path) if path.exists() else []
    rows.append(
        {"ID": log.lead_id, "일자": log.contacted_on, "채널": log.channel, "내용": log.summary, "결과": log.outcome}
    )
    return write_csv_rows(path, CONTACT_HEADERS, rows)


def update_lead_fields(path: Path, lead_id: str, updates: dict[str, str]) -> bool:
    """leads.csv의 특정 공급처 행 일부 칸만 갱신한다 (예: 단계, 다음액션)."""
    rows = read_csv_rows(path)
    found = False
    for row in rows:
        if row.get("ID") == lead_id:
            row.update({k: v for k, v in updates.items() if v is not None})
            found = True
    if found:
        write_csv_rows(path, LEAD_HEADERS, rows)
    return found


def record_history(path: Path, evaluations: list[LeadEvaluation], today: date) -> Path:
    """오늘 날짜의 퍼널 스냅샷을 누적한다 (같은 날 재실행 시 덮어씀)."""
    rows = [r for r in (read_csv_rows(path) if path.exists() else []) if r.get("일자") != today.isoformat()]
    snapshot: dict = {"일자": today.isoformat()}
    for stage in SourcingStage:
        snapshot[stage.value] = sum(1 for e in evaluations if e.lead.stage == stage)
    for grade in SourcingGrade:
        snapshot[grade.value] = sum(1 for e in evaluations if e.grade == grade)
    rows.append(snapshot)
    rows.sort(key=lambda r: r["일자"])
    return write_csv_rows(path, HISTORY_HEADERS, rows)
