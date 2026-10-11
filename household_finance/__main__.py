"""명령줄 도구: python -m household_finance {build,import,new-month} ..."""

from __future__ import annotations

import argparse
import sys

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
    except (ValueError, KeyError, FileNotFoundError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
