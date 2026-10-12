"""명령줄 도구: python -m household_finance {build,import,new-month,serve,demo,backup,scheduler,report} ..."""

from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path

from household_finance.importer import import_statement, new_month
from household_finance.workbook import build_workbook


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m household_finance", description="우리집 주식회사 자산관리 도구")
    sub = parser.add_subparsers(dest="command", required=True)

    b = sub.add_parser("build", help="새 자산관리 스프레드시트 생성")
    b.add_argument("--out", required=True, help="저장할 .xlsx 경로")
    b.add_argument("--blank", action="store_true", help="샘플 데이터 없이 빈 템플릿으로 생성")
    b.add_argument("--month", help="대시보드 기준월 (yyyy-mm, 기본: 빈 템플릿은 지난달)")

    i = sub.add_parser("import", help="카드·은행 내역(CSV/xlsx)을 자동 분류해 거래내역에 추가")
    i.add_argument("workbook", help="자산관리 .xlsx 경로")
    i.add_argument("statement", help="카드·은행 내역 파일 (.csv 또는 .xlsx)")
    i.add_argument("--member", required=True, choices=["본인", "배우자", "공동"], help="이 내역의 구성원")
    i.add_argument("--payment", default="", help="결제수단 이름 (예: 신한카드)")
    i.add_argument("--dry-run", action="store_true", help="저장하지 않고 결과만 미리보기")
    i.add_argument("--date-col", help="날짜 열 이름 (자동 인식 실패 시)")
    i.add_argument("--desc-col", help="내용 열 이름 (자동 인식 실패 시)")
    i.add_argument("--amount-col", help="금액 열 이름 (자동 인식 실패 시)")

    n = sub.add_parser("new-month", help="다음 달 스냅샷 행 생성 + 대시보드 기준월 변경")
    n.add_argument("workbook", help="자산관리 .xlsx 경로")
    n.add_argument("--month", help="만들 달 (yyyy-mm, 기본: 마지막 스냅샷의 다음 달)")

    w = sub.add_parser("serve", help="웹앱 실행 (브라우저로 http://주소:포트 접속)")
    w.add_argument("--db", default="우리집.db", help="데이터베이스 파일 (없으면 새로 만듦)")
    w.add_argument("--host", default="127.0.0.1", help="같은 와이파이의 다른 기기에서 접속하려면 0.0.0.0")
    w.add_argument("--port", type=int, default=8000)
    w.add_argument("--from-workbook", help="데이터베이스가 비어 있으면 이 엑셀 파일로 채움")
    w.add_argument("--https", action="store_true", help="HTTPS 리버스 프록시(Caddy 등) 뒤에서 실행: 보안 쿠키·프록시 헤더 사용")

    k = sub.add_parser("backup", help="데이터베이스 백업 (사용 중에도 안전)")
    k.add_argument("--db", default="우리집.db")
    k.add_argument("--out-dir", default="백업")
    k.add_argument("--keep", type=int, default=30, help="남겨 둘 백업 개수")

    r = sub.add_parser("scheduler", help="예약 작업 실행: 매일 백업, 매월 결산 리포트 메일 (HH_SMTP_* 환경변수)")
    r.add_argument("--db", default="우리집.db")
    r.add_argument("--backup-dir", help="백업 폴더 (없으면 백업 안 함)")
    r.add_argument("--keep", type=int, default=30)
    r.add_argument("--report-day", type=int, default=1, help="매월 며칠에 리포트를 보낼지 (1~28)")

    rp = sub.add_parser("report", help="결산 리포트를 HTML 파일로 저장하거나 메일로 보냄")
    rp.add_argument("--db", default="우리집.db")
    rp.add_argument("--month", help="기준월 (기본: 마지막 결산월)")
    rp.add_argument("--out", help="HTML로 저장할 경로")
    rp.add_argument("--send", action="store_true", help="HH_SMTP_* 설정으로 메일 발송")

    d = sub.add_parser("demo", help="서버 없이 열어 보는 체험판 HTML 생성 (샘플 데이터)")
    d.add_argument("--out", default="우리집_체험판.html")

    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            path = build_workbook(args.out, sample=not args.blank, base_month=args.month)
            print(f"생성 완료: {path}")
        elif args.command == "import":
            result = import_statement(args.workbook, args.statement, args.member, args.payment, args.dry_run,
                                      date_col=args.date_col, desc_col=args.desc_col, amount_col=args.amount_col)
            label = "추가 예정" if args.dry_run else "추가"
            print(f"{label} {len(result.added)}건 · 중복 제외 {result.duplicates}건 · 건너뜀 {len(result.skipped)}건")
            for t in result.added:
                print(f"  {t.day} {t.desc[:24]:<24} {t.amount:>12,}원 → {t.category}")
            if result.uncategorized:
                print(f"⚠ 미분류 {len(result.uncategorized)}건: [분류규칙] 시트에 키워드를 추가하거나 거래내역에서 직접 지정하세요.")
            for line in result.skipped:
                print(f"  건너뜀 - {line}")
        elif args.command == "new-month":
            month, count = new_month(args.workbook, args.month)
            print(f"{month} 스냅샷 {count}행 생성 (직전 달 잔액 복사). 바뀐 잔액만 수정하세요. 대시보드 기준월 → {month}")
        elif args.command == "demo":
            from household_finance.webapp.demo import build_demo
            print(f"체험판 생성: {build_demo(args.out)}")
        elif args.command == "serve":
            return serve(args)
        elif args.command == "backup":
            from household_finance.store import Store
            print(f"백업 완료: {Store(args.db).backup(args.out_dir, args.keep)}")
        elif args.command == "scheduler":
            from household_finance.scheduler import loop
            if not 1 <= args.report_day <= 28:
                raise ValueError("--report-day는 1~28 사이여야 합니다.")
            loop(args.db, args.report_day, args.backup_dir, args.keep)
        elif args.command == "report":
            return report_cmd(args)
    except (ValueError, KeyError, FileNotFoundError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1
    return 0


def serve(args) -> int:
    import uvicorn

    from household_finance.model import load_workbook_dataset
    from household_finance.store import Store
    from household_finance.webapp.app import create_app

    if args.from_workbook:
        store = Store(args.db)
        if store.is_empty():
            store.replace_dataset(load_workbook_dataset(args.from_workbook))
            print(f"엑셀 데이터를 가져왔습니다: {args.from_workbook}")
        store.close()
    # 이 컴퓨터 밖에서 접속할 수 있게 열 때는, 처음 설정을 아무나 하지 못하도록 설치 코드를 요구한다
    setup_code = None
    store = Store(args.db)
    if args.host not in ("127.0.0.1", "localhost", "::1") and not store.users():
        setup_code = secrets.token_hex(3).upper()
        print(f"처음 설정용 설치 코드: {setup_code}  (처음 설정 화면에 입력하세요. 서버를 다시 켜면 바뀝니다.)")
    store.close()
    scheme = "https" if args.https else "http"
    print(f"우리집 주식회사 웹앱: {scheme}://{'localhost' if args.host in ('127.0.0.1', '0.0.0.0') else args.host}:{args.port}")
    uvicorn.run(create_app(args.db, setup_code=setup_code, secure_cookies=args.https), host=args.host, port=args.port,
                log_level="warning", proxy_headers=args.https, forwarded_allow_ips="*" if args.https else None)
    return 0


def report_cmd(args) -> int:
    from household_finance import report
    from household_finance.engine import compute
    from household_finance.store import Store

    subject, html, text = report.build(compute(Store(args.db).load_dataset(), "전체", args.month))
    if args.out:
        Path(args.out).write_text(f"<!doctype html><meta charset='utf-8'><title>{subject}</title>{html}", encoding="utf-8")
        print(f"리포트 저장: {args.out}")
    if args.send:
        cfg = report.MailConfig.from_env()
        if cfg is None:
            raise ValueError("메일 설정이 없습니다. HH_SMTP_HOST·HH_SMTP_USER·HH_SMTP_PASSWORD·HH_MAIL_TO 환경변수를 지정하세요.")
        report.send(cfg, subject, html, text)
        print(f"리포트 발송: {', '.join(cfg.to)}")
    if not args.out and not args.send:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
