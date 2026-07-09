"""사용자별 맞춤 리포트 정기 발송 (헤드리스, 스케줄용).

Supabase의 confirmed 구독자 전원에게 각자 포트폴리오 분석 리포트를 메일로 보낸다.
Windows 작업 스케줄러가 run_users_report.cmd 로 주기 호출한다.
"""

from __future__ import annotations

import sys

import common  # noqa: F401 (.env/secrets + sys.path)
import emailer
import reports


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    cfg = emailer.load_config()
    base_url = cfg.get("base_url", "")
    print("사용자별 맞춤 리포트 발송 시작...")
    res = reports.send_user_reports(
        base_url, progress=lambda f, m: print(f"  {int(f*100):3d}% {m}"))
    print(f"완료: 성공 {res['sent']} / 실패 {res['failed']} "
          f"/ 건너뜀 {res['skipped']} (총 {res['total']})")
    for e in res["errors"][:20]:
        print("  실패:", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
