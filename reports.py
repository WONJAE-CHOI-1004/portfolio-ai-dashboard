"""사용자별 맞춤 리포트 생성·발송 (멀티유저).

Supabase의 confirmed 구독자를 돌며 각자의 포트폴리오를 분석해 개인 메일로 보낸다.
대시보드 버튼과 스케줄 작업(run_users_report.py)이 공용으로 사용한다.

주의(무료 등급): 사용자 1명당 Gemini 호출이 여러 번 → 사용자가 많으면 일일 한도
초과 가능. 소규모 MVP 전제. 규모가 커지면 유료 LLM 필요.
"""

from __future__ import annotations

from typing import Callable

import emailer
import pipeline
import store


def send_user_reports(base_url: str = "",
                      progress: Callable[[float, str], None] | None = None) -> dict:
    users = store.list_confirmed()
    n = len(users)
    sent, failed, skipped = 0, 0, 0
    errors: list[str] = []

    for i, u in enumerate(users):
        email = u.get("email", "")
        holdings = u.get("holdings") or []
        token = u.get("token", "")
        if progress:
            progress(i / max(n, 1), f"{email} 분석 중 ({i+1}/{n})")
        if not holdings:
            skipped += 1
            continue
        try:
            result = pipeline.run_portfolio(holdings, with_synergy=True)
            subject = emailer.default_subject(result)
            body = emailer.default_body(result)
            if base_url and token:
                b = base_url.rstrip("/")
                body += (f"\n\n────────\n종목 수정: {b}/?edit={token}\n"
                         f"수신거부: {b}/?unsub={token}")
            ok, msg = emailer.send(subject, body, recipient=email)
            if ok:
                sent += 1
            else:
                failed += 1
                errors.append(f"{email}: {msg}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            errors.append(f"{email}: {e}")

    if progress:
        progress(1.0, "완료")
    return {"total": n, "sent": sent, "failed": failed,
            "skipped": skipped, "errors": errors}
