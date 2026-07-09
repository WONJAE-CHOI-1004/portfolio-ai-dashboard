"""구독자 관리 — 더블 옵트인(구독 확인) + 원클릭 수신거부.

- subscribe(email): 대기(pending) 등록 + 확인 토큰 발급 → 확인 메일 발송
- confirm(token): 확인 완료(confirmed)
- unsubscribe(token): 수신거부(unsubscribed)
- send_newsletter(...): confirmed 구독자에게만 발송, 각 메일에 수신거부 링크 포함

주의: 개인 Gmail은 하루 발송 한도(~500)·스팸 차단 위험이 있어 소규모에만 적합.
대규모는 전용 서비스(SendGrid/Brevo/SES)로 emailer 백엔드를 교체할 것.
저장: subscribers.json (개인정보 → .gitignore로 커밋 제외).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import secrets

import emailer

SUBS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "subscribers.json")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def load() -> dict:
    if os.path.exists(SUBS_PATH):
        try:
            with open(SUBS_PATH, encoding="utf-8-sig") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save(subs: dict) -> None:
    with open(SUBS_PATH, "w", encoding="utf-8") as f:
        json.dump(subs, f, ensure_ascii=False, indent=2)


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match((email or "").strip()))


def subscribe(email: str) -> tuple[str, str]:
    """대기 등록(또는 재발급). 반환: (상태, 토큰).
    상태: 'new'(새 대기) / 'already'(이미 확인됨) / 'resent'(대기 재발급)."""
    email = (email or "").strip().lower()
    subs = load()
    entry = subs.get(email)
    if entry and entry.get("status") == "confirmed":
        return "already", entry["token"]
    token = (entry or {}).get("token") or secrets.token_urlsafe(16)
    state = "resent" if entry else "new"
    subs[email] = {"status": "pending", "token": token,
                   "created": (entry or {}).get("created", _now()),
                   "confirmed": None}
    save(subs)
    return state, token


def _find_by_token(subs: dict, token: str) -> str | None:
    for email, e in subs.items():
        if e.get("token") == token:
            return email
    return None


def confirm(token: str) -> tuple[bool, str]:
    subs = load()
    email = _find_by_token(subs, token)
    if not email:
        return False, ""
    subs[email]["status"] = "confirmed"
    subs[email]["confirmed"] = _now()
    save(subs)
    return True, email


def unsubscribe(token: str) -> tuple[bool, str]:
    subs = load()
    email = _find_by_token(subs, token)
    if not email:
        return False, ""
    subs[email]["status"] = "unsubscribed"
    save(subs)
    return True, email


def confirmed() -> list[dict]:
    return [{"email": e, "token": v["token"]}
            for e, v in load().items() if v.get("status") == "confirmed"]


def counts() -> dict:
    subs = load()
    c = {"confirmed": 0, "pending": 0, "unsubscribed": 0}
    for v in subs.values():
        c[v.get("status", "pending")] = c.get(v.get("status", "pending"), 0) + 1
    return c


# ── 메일 발송 ───────────────────────────────────────────────────────
def send_confirmation(email: str, token: str, base_url: str,
                      cfg: dict | None = None) -> tuple[bool, str]:
    link = f"{base_url.rstrip('/')}/?confirm={token}"
    body = (
        "포트폴리오 리포트 구독을 신청하셨습니다.\n\n"
        "아래 링크를 클릭하시면 구독이 완료됩니다(본인 확인):\n"
        f"{link}\n\n"
        "본인이 신청하지 않았다면 이 메일을 무시하세요.\n"
        "— 포트폴리오 AI 리포트")
    return emailer.send("[구독 확인] 포트폴리오 리포트", body, cfg, recipient=email)


def send_newsletter(subject: str, body: str, base_url: str,
                    cfg: dict | None = None) -> dict:
    """confirmed 구독자에게 발송. 각 메일에 수신거부 링크 첨부. 결과 요약 반환."""
    cfg = cfg or emailer.load_config()
    targets = confirmed()
    sent, failed = 0, 0
    errors = []
    for t in targets:
        unsub = f"{base_url.rstrip('/')}/?unsub={t['token']}"
        full = f"{body}\n\n────────\n수신거부: {unsub}"
        ok, msg = emailer.send(subject, full, cfg, recipient=t["email"])
        if ok:
            sent += 1
        else:
            failed += 1
            errors.append(f"{t['email']}: {msg}")
    return {"total": len(targets), "sent": sent, "failed": failed, "errors": errors}
