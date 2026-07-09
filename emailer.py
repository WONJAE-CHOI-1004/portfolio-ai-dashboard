"""이메일 발송 (Gmail SMTP). 대시보드에서 직접 작성해 보내거나, 가격 알림을 메일로.

주의: Gmail은 일반 비밀번호가 아니라 '앱 비밀번호(App Password)'가 필요하다.
  발급: Google 계정 → 보안 → 2단계 인증 켜기 → 앱 비밀번호 생성(16자리).
설정은 email_config.json에 로컬 저장된다(평문). 개인 PC 전용으로만 사용할 것.
"""

from __future__ import annotations

import json
import os
import smtplib
from email.mime.text import MIMEText
from email.utils import formataddr

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "email_config.json")


def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8-sig") as f:
                return json.load(f)
        except Exception:
            pass
    return {"smtp_host": "smtp.gmail.com", "smtp_port": 465,
            "sender": "", "app_password": "", "recipient": "",
            "alerts_enabled": False, "weekly_report_enabled": False}


def save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def send(subject: str, body: str, cfg: dict | None = None) -> tuple[bool, str]:
    """메일 발송. (성공여부, 메시지) 반환. 실제 전송은 사용자 확인 후에만 호출."""
    cfg = cfg or load_config()
    sender = (cfg.get("sender") or "").strip()
    pw = (cfg.get("app_password") or "").strip()
    recipient = (cfg.get("recipient") or sender).strip()
    if not sender or not pw:
        return False, "보내는 사람 이메일과 앱 비밀번호를 먼저 설정하세요."
    if not recipient:
        return False, "받는 사람 이메일이 없습니다."

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = formataddr(("포트폴리오 대시보드", sender))
    msg["To"] = recipient
    host = cfg.get("smtp_host", "smtp.gmail.com")
    port = int(cfg.get("smtp_port", 465))
    try:
        with smtplib.SMTP_SSL(host, port, timeout=20) as s:
            s.login(sender, pw)
            s.sendmail(sender, [recipient], msg.as_string())
        return True, f"{recipient} 로 발송 완료"
    except smtplib.SMTPAuthenticationError:
        return False, "인증 실패: Gmail '앱 비밀번호'가 맞는지 확인하세요(일반 비번 아님)."
    except Exception as e:  # noqa: BLE001
        return False, f"발송 실패: {e}"


def default_subject(result: dict) -> str:
    d = (result or {}).get("trade_date", "")
    return f"[포트폴리오 리포트] {d}"


def default_body(result: dict) -> str:
    """최신 분석 결과로 메일 본문 초안을 만든다."""
    if not result:
        return "분석 결과가 없습니다. 대시보드에서 먼저 분석을 실행하세요."
    lines = [f"■ 포트폴리오 리포트 (기준일 {result.get('trade_date','')})",
             f"  분석 시각: {result.get('generated_at','')}", ""]
    tot = result.get("totals")
    if tot:
        lines += [f"[전체] 평가 {tot['mv_krw']:,.0f}원 / 매입 {tot['cost_krw']:,.0f}원 "
                  f"→ 손익 {tot['pnl_krw']:+,.0f}원 ({tot['pnl_pct']:+.2f}%)", ""]
    lines.append("[종목별]")
    for s in result.get("stocks", []):
        f = s.get("fast", {})
        pnl = (f"{s['pnl_pct']:+.1f}%" if s.get("pnl_pct") is not None else "-")
        v = s.get("valuation") or {}
        lines.append(f"  · {s.get('name','?')}({s.get('ticker','')}) "
                     f"AI:{f.get('rating','-')} 손익:{pnl} 판정:{v.get('verdict','-')}")
    diag = result.get("diagnostics")
    if diag:
        lines += ["", f"[분산 진단] 유효 베팅 {diag['effective_bets']}/{diag['n']} · "
                  f"최대VIF {diag['max_vif']} · 판정 {', '.join(diag['flags'])}"]
    if result.get("synergy"):
        lines += ["", "[종목 간 시너지]", result["synergy"]]
    lines += ["", "— 참고용 분석이며 투자 판단·책임은 본인에게 있습니다."]
    return "\n".join(lines)
