"""Supabase(무료 PostgreSQL) 기반 사용자·포트폴리오 저장소 (멀티유저 MVP).

파일 저장은 클라우드에서 재시작 시 날아가므로, 각 사용자의 이메일·포트폴리오·
구독상태를 Supabase에 영속 저장한다. REST API(PostgREST)만 사용해 의존성 최소화.

자격증명(환경변수/시크릿):
  SUPABASE_URL = https://<프로젝트>.supabase.co
  SUPABASE_KEY = service_role 키 (서버측 전용, 절대 브라우저/저장소 노출 금지)

테이블 스키마(subscribers): id, email(unique), holdings(jsonb),
  status(pending|confirmed|unsubscribed), token, created_at, confirmed_at
"""

from __future__ import annotations

import datetime as dt
import os
import secrets

import requests

TABLE = "subscribers"


def _ensure_env() -> None:
    """로컬 .env 를 읽어 SUPABASE_* 를 채운다(아직 없을 때만).
    클라우드에선 common.apply_secrets 가 st.secrets 를 이미 채워둔다."""
    if os.environ.get("SUPABASE_URL"):
        return
    try:
        from dotenv import load_dotenv
        here = os.path.dirname(os.path.abspath(__file__))
        load_dotenv(os.path.join(here, ".env"))
    except Exception:
        pass


_ensure_env()


def _base() -> tuple[str, str]:
    return os.environ.get("SUPABASE_URL", "").rstrip("/"), os.environ.get("SUPABASE_KEY", "")


def is_configured() -> bool:
    url, key = _base()
    return bool(url and key)


def _headers(key: str, prefer: str | None = None) -> dict:
    h = {"apikey": key, "Authorization": f"Bearer {key}",
         "Content-Type": "application/json"}
    if prefer:
        h["Prefer"] = prefer
    return h


def _endpoint(url: str) -> str:
    return f"{url}/rest/v1/{TABLE}"


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _get(params: dict) -> list:
    url, key = _base()
    r = requests.get(_endpoint(url), headers=_headers(key), params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def get_by_token(token: str) -> dict | None:
    rows = _get({"token": f"eq.{token}", "select": "*"})
    return rows[0] if rows else None


def get_by_email(email: str) -> dict | None:
    rows = _get({"email": f"eq.{email.strip().lower()}", "select": "*"})
    return rows[0] if rows else None


def _patch(email: str, fields: dict) -> list:
    url, key = _base()
    r = requests.patch(_endpoint(url), headers=_headers(key, "return=representation"),
                       params={"email": f"eq.{email.strip().lower()}"},
                       json=fields, timeout=15)
    r.raise_for_status()
    return r.json()


def register(email: str, holdings: list) -> tuple[str, str]:
    """이메일 + 포트폴리오 등록(또는 갱신). 반환 (상태, 토큰).
    상태: new(신규 대기) / resent(대기 재발급) / already(이미 확인됨→포폴만 갱신)."""
    email = email.strip().lower()
    existing = get_by_email(email)
    if existing:
        token = existing["token"]
        if existing.get("status") == "confirmed":
            _patch(email, {"holdings": holdings})
            return "already", token
        _patch(email, {"holdings": holdings, "status": "pending"})
        return "resent", token
    token = secrets.token_urlsafe(16)
    url, key = _base()
    payload = {"email": email, "holdings": holdings, "status": "pending",
               "token": token, "created_at": _now()}
    r = requests.post(_endpoint(url), headers=_headers(key, "return=representation"),
                      json=payload, timeout=15)
    r.raise_for_status()
    return "new", token


def confirm(token: str) -> tuple[bool, str]:
    row = get_by_token(token)
    if not row:
        return False, ""
    _patch(row["email"], {"status": "confirmed", "confirmed_at": _now()})
    return True, row["email"]


def unsubscribe(token: str) -> tuple[bool, str]:
    row = get_by_token(token)
    if not row:
        return False, ""
    _patch(row["email"], {"status": "unsubscribed"})
    return True, row["email"]


def set_subscribed(email: str, on: bool) -> None:
    """정기 이메일 구독 on/off (이메일 확인 링크 없이 토글)."""
    fields = {"status": "confirmed"} if on else {"status": "unsubscribed"}
    if on:
        fields["confirmed_at"] = _now()
    _patch(email, fields)


def update_holdings(token: str, holdings: list) -> tuple[bool, str]:
    row = get_by_token(token)
    if not row:
        return False, ""
    _patch(row["email"], {"holdings": holdings})
    return True, row["email"]


def list_confirmed() -> list[dict]:
    return _get({"status": "eq.confirmed", "select": "email,holdings,token"})


def counts() -> dict:
    c = {"confirmed": 0, "pending": 0, "unsubscribed": 0}
    try:
        for r in _get({"select": "status"}):
            s = r.get("status", "pending")
            c[s] = c.get(s, 0) + 1
    except Exception:
        pass
    return c
