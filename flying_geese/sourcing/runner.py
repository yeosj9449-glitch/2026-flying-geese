"""소싱 대시보드 실행 진입점 (CLI `sourcing`, `sourcing-log`에서 사용)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from flying_geese.models import ContactLog, LeadEvaluation
from flying_geese.sourcing import store
from flying_geese.sourcing.criteria import evaluate_leads
from flying_geese.sourcing.dashboard import SourcingSummary, generate_sourcing_dashboard, summarize

DEFAULT_OUTPUT = Path(__file__).resolve().parents[2] / "output" / "sourcing_dashboard.xlsx"


@dataclass
class SourcingReport:
    evaluations: list[LeadEvaluation]
    summary: SourcingSummary
    dashboard_path: Path
    using_examples: bool


def run_sourcing_dashboard(
    sourcing_dir: Path = store.DEFAULT_SOURCING_DIR,
    output_path: Path = DEFAULT_OUTPUT,
    today: date | None = None,
) -> SourcingReport:
    today = today or date.today()
    leads_path, using_examples = store.resolve(sourcing_dir, "leads")
    if not leads_path.exists():
        raise FileNotFoundError(f"공급처 파일이 없습니다: {leads_path}")
    contacts_path, _ = store.resolve(sourcing_dir, "contacts")
    samples_path, _ = store.resolve(sourcing_dir, "samples")

    leads = store.load_leads(leads_path)
    contacts = store.load_contacts(contacts_path)
    samples = store.load_samples(samples_path)
    evaluations = evaluate_leads(leads, today, samples)

    history_path = sourcing_dir / "history.csv"
    if not using_examples:
        # 예시 데이터로 돌릴 때는 실제 퍼널 추이를 오염시키지 않도록 기록하지 않는다.
        store.record_history(history_path, evaluations, today)

    dashboard = generate_sourcing_dashboard(
        evaluations, contacts, samples, output_path, today,
        history_path=history_path, using_examples=using_examples,
    )
    return SourcingReport(evaluations, summarize(evaluations, contacts, today), dashboard, using_examples)


def log_contact(
    lead_id: str,
    channel: str,
    summary: str,
    outcome: str = "",
    stage: str | None = None,
    next_action: str | None = None,
    next_action_date: str | None = None,
    sourcing_dir: Path = store.DEFAULT_SOURCING_DIR,
    today: date | None = None,
) -> Path:
    """연락 1건을 contacts.csv에 누적하고, 필요하면 leads.csv의 단계/다음액션도 갱신한다."""
    leads_path = sourcing_dir / "leads.csv"
    if not leads_path.exists():
        raise FileNotFoundError(
            f"{leads_path}가 없습니다. leads.example.csv를 leads.csv로 복사해 실제 공급처를 채운 뒤 사용하세요."
        )
    if not any(lead.lead_id == lead_id for lead in store.load_leads(leads_path)):
        raise ValueError(f"leads.csv에 없는 공급처 ID입니다: {lead_id}")

    contacts_path = sourcing_dir / "contacts.csv"
    store.append_contact(contacts_path, ContactLog(lead_id, today or date.today(), channel, summary, outcome))
    updates = {"단계": stage, "다음액션": next_action, "다음액션일": next_action_date}
    if any(v is not None for v in updates.values()):
        store.update_lead_fields(leads_path, lead_id, updates)
    return contacts_path
