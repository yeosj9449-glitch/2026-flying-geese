from datetime import date
from pathlib import Path

from flying_geese.marketing.influencer import Influencer, evaluate_influencer, load_influencers, persona_fit

TODAY = date(2026, 10, 20)


def test_persona_fit_prioritizes_weaning_age():
    assert persona_fit(12) == (1.0, "A 이유식맘")
    assert persona_fit(36)[1].startswith("B")
    assert persona_fit(None)[0] == 0.5


def test_priority_prefers_engaged_micro_with_weaning_child():
    micro = Influencer("@a", followers=30000, avg_likes=1500, avg_comments=100, child_months=10)
    macro = Influencer("@b", followers=400000, avg_likes=4000, avg_comments=100, child_months=10)
    assert evaluate_influencer(micro, TODAY).priority > evaluate_influencer(macro, TODAY).priority


def test_todos_and_groupbuy_candidate():
    dm = Influencer("@c", status="DM발송", dm_sent_on=date(2026, 10, 10))
    assert "재연락" in evaluate_influencer(dm, TODAY).todos[0]
    shipped = Influencer("@d", status="발송완료", shipped_on=date(2026, 10, 1))
    assert "리마인드" in evaluate_influencer(shipped, TODAY).todos[0]
    posted = Influencer("@e", followers=20000, avg_likes=800, status="게시완료", groupbuy_ok=True, coupon_code="E10")
    ev = evaluate_influencer(posted, TODAY)
    assert ev.groupbuy_candidate and any("공구" in t for t in ev.todos)


def test_load_example_csv():
    rows = load_influencers(Path(__file__).resolve().parents[1] / "data" / "marketing" / "influencers.example.csv")
    assert rows[0].handle.startswith("@") and rows[0].roi is not None
