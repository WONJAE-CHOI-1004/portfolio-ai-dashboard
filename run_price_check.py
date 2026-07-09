"""적정가(관심 매수가) 도달 감시 — 자주(매일) 실행. LLM 없음, 가볍고 빠름.

watch_targets.json의 각 종목 현재가를 확인해, 설정한 관심 매수가 이하로
내려오면 알림(Windows 팝업 + cache/alerts.json 기록)을 남긴다.
Windows 작업 스케줄러가 run_price_check.cmd로 하루 1~수회 호출한다.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys

import common  # noqa: F401 (.env + sys.path)
import valuation
import notify

ALERTS_PATH = os.path.join(common.CACHE_DIR, "alerts.json")


def _price(ticker: str) -> float | None:
    import yfinance as yf
    try:
        return float(yf.Ticker(ticker).fast_info.last_price)
    except Exception:
        return None


def load_alerts() -> list:
    if os.path.exists(ALERTS_PATH):
        try:
            with open(ALERTS_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    targets = valuation.load_watch()
    if not targets:
        print("감시 대상이 없습니다. 대시보드 7번 섹션에서 관심 매수가를 등록하세요.")
        return 0

    today = dt.date.today().isoformat()
    alerts = load_alerts()
    fired_today = {(a["ticker"], a["date"]) for a in alerts}
    new_hits = []

    for tkr, cfg in targets.items():
        buy = cfg.get("buy_price")
        price = _price(tkr)
        if buy is None or price is None:
            continue
        status = "도달" if price <= buy else "감시중"
        print(f"{tkr:8} 현재 {price:.2f} / 관심 {buy:.2f} → {status}")
        if price <= buy and (tkr, today) not in fired_today:
            hit = {"ticker": tkr, "date": today,
                   "time": dt.datetime.now().strftime("%H:%M"),
                   "price": round(price, 2), "buy_price": buy,
                   "note": cfg.get("note", "")}
            alerts.append(hit)
            new_hits.append(hit)

    if new_hits:
        with open(ALERTS_PATH, "w", encoding="utf-8") as f:
            json.dump(alerts, f, ensure_ascii=False, indent=2)
        lines = [f"{h['ticker']} {h['price']} (관심 {h['buy_price']} 이하!)" for h in new_hits]
        notify.notify("📉 관심 매수가 도달", " / ".join(lines))
        print(f"[알림] {len(new_hits)}건 발생: {', '.join(h['ticker'] for h in new_hits)}")
        # 이메일 알림(설정에서 켠 경우에만)
        try:
            import emailer
            cfg = emailer.load_config()
            if cfg.get("alerts_enabled") and cfg.get("sender") and cfg.get("app_password"):
                body = "관심 매수가에 도달했습니다.\n\n" + "\n".join(lines) + \
                       "\n\n— 참고용 알림이며 투자 판단·책임은 본인에게 있습니다."
                ok, m = emailer.send("📉 관심 매수가 도달 알림", body, cfg)
                print(f"[이메일] {m}")
        except Exception as e:  # noqa: BLE001
            print(f"[이메일] 발송 시도 실패: {e}")
    else:
        print("신규 알림 없음.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
