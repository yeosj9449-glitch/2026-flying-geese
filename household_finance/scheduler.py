"""예약 작업 - 매일 DB 백업, 매월 결산 리포트 메일.

python -m household_finance scheduler --db 우리집.db --backup-dir 백업 --report-day 1
한 시간마다 깨어나 할 일이 있는지 본다. 이미 한 일은 DB에 기록해 두므로 재시작해도 두 번 하지 않고,
메일 발송이 실패하면 기록하지 않아 다음 시간에 다시 시도한다.
"""

from __future__ import annotations

import logging
import time
from datetime import date
from pathlib import Path

from household_finance import report
from household_finance.engine import compute
from household_finance.store import Store

log = logging.getLogger("household_finance.scheduler")


def run_once(store: Store, today: date, mail: report.MailConfig | None, report_day: int = 1,
             backup_dir: str | Path | None = None, keep: int = 30, sender=report.send) -> list[str]:
    done = []
    if backup_dir and store.get_flag("backup_date") != today.isoformat():
        path = store.backup(backup_dir, keep)
        store.set_flag("backup_date", today.isoformat())
        done.append(f"백업: {path}")
    this_month = f"{today.year}-{today.month:02d}"
    if mail and today.day >= report_day and store.get_flag("report_sent") != this_month:
        if store.is_empty():
            return done
        d = compute(store.load_dataset(), "전체", today=today)
        subject, html, text = report.build(d)
        try:
            sender(mail, subject, html, text)
        except Exception as exc:   # 네트워크·인증 오류: 기록하지 않고 다음 시간에 다시 시도
            log.warning("리포트 메일 발송 실패 (다음 시간에 다시 시도): %s", exc)
            done.append(f"리포트 발송 실패: {exc}")
            return done
        store.set_flag("report_sent", this_month)
        done.append(f"리포트 발송: {d['base_month']} → {', '.join(mail.to)}")
    return done


def loop(db: str | Path, report_day: int, backup_dir: str | None, keep: int, interval: int = 3600) -> None:
    mail = report.MailConfig.from_env()
    print(f"예약 작업 시작 · 백업: {backup_dir or '안 함'} · 리포트 메일: "
          f"{'매월 ' + str(report_day) + '일 → ' + ', '.join(mail.to) if mail else '안 함 (HH_SMTP_HOST·HH_MAIL_TO 미설정)'}")
    while True:
        store = Store(db)
        try:
            for line in run_once(store, date.today(), mail, report_day, backup_dir, keep):
                print(line, flush=True)
        finally:
            store.close()
        time.sleep(interval)
