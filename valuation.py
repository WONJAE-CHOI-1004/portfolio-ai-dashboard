"""밸류에이션 기반 '적정 매수가' 산정 + 모니터링 대상 관리.

섹터/종목을 추천해도 지금 밸류에이션이 비싸면(현재가가 적정가보다 높으면)
바로 사는 건 불리하다. 그래서 각 종목의 '관심 매수가(watch price)'를 계산하고,
그 가격에 도달하면 알림을 주도록 감시 대상에 등록한다.

적정가 근거(휴리스틱, 참고용):
- 애널리스트 목표주가(평균/최저/최고)  ← yfinance
- 선행 PER·EPS 로 본 이익 기반 가치
- 관심 매수가 = 적정가 대비 10% 안전마진 아래
"""

from __future__ import annotations

import json
import os

import common

WATCH_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "watch_targets.json")
MARGIN = 0.90  # 적정가 대비 10% 안전마진


def fair_value(ticker: str) -> dict:
    """종목의 밸류에이션 요약 + 관심 매수가 + 판정."""
    import yfinance as yf
    tk = yf.Ticker(ticker)
    try:
        info = tk.get_info() or {}
    except Exception:
        info = {}
    price = info.get("currentPrice") or info.get("regularMarketPrice")
    if not price:
        try:
            price = float(tk.fast_info.last_price)
        except Exception:
            price = None

    tgt_mean = info.get("targetMeanPrice")
    tgt_low = info.get("targetLowPrice")
    tgt_high = info.get("targetHighPrice")
    n_analyst = info.get("numberOfAnalystOpinions")
    rec_key = info.get("recommendationKey")
    fwd_pe = info.get("forwardPE")
    trail_pe = info.get("trailingPE")
    fwd_eps = info.get("forwardEps")

    # 적정가: 애널리스트 평균 목표주가 우선, 없으면 선행 PER×EPS, 그래도 없으면(ETF 등)
    # 200일 이동평균을 기술적 관심가로 사용.
    fair = tgt_mean
    fair_basis = "애널리스트 평균 목표주가"
    is_technical = False
    if not fair and fwd_eps and fwd_eps > 0:
        fair = fwd_eps * (fwd_pe or 15)
        fair_basis = "선행 EPS × 선행 PER"
    if not fair:
        try:
            sma200 = float(tk.history(period="1y", auto_adjust=True)["Close"]
                           .tail(200).mean())
            fair = sma200
            fair_basis = "200일 이동평균(기술적)"
            is_technical = True
        except Exception:
            fair = None

    # 기술적 관심가는 그 수준(눌림목) 자체, 밸류에이션 적정가는 10% 안전마진 아래
    watch_buy = round(fair * (1.0 if is_technical else MARGIN), 2) if fair else None
    upside = ((tgt_mean / price - 1) * 100) if (tgt_mean and price) else None

    # 판정
    verdict = "중립"
    if price and fair:
        if price >= fair * 1.02 or (rec_key in ("sell", "underperform")):
            verdict = "밸류에이션 부담 — 대기"
        elif upside is not None and upside >= 15:
            verdict = "매수 매력 구간"
        elif watch_buy and price <= watch_buy:
            verdict = "관심가 이하 — 매수 검토"
    now_below = bool(watch_buy and price and price <= watch_buy)

    return {
        "ticker": ticker,
        "price": price,
        "currency": info.get("currency") or "USD",
        "target_mean": tgt_mean, "target_low": tgt_low, "target_high": tgt_high,
        "n_analyst": n_analyst, "recommendation": rec_key,
        "forward_pe": fwd_pe, "trailing_pe": trail_pe,
        "fair_value": round(fair, 2) if fair else None,
        "fair_basis": fair_basis,
        "watch_buy": watch_buy,
        "upside_pct": round(upside, 1) if upside is not None else None,
        "verdict": verdict,
        "now_below_watch": now_below,
    }


# ── 감시 대상(watch list) 저장/로드 ─────────────────────────────────
def load_watch() -> dict:
    if os.path.exists(WATCH_PATH):
        try:
            with open(WATCH_PATH, encoding="utf-8-sig") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_watch(targets: dict) -> None:
    with open(WATCH_PATH, "w", encoding="utf-8") as f:
        json.dump(targets, f, ensure_ascii=False, indent=2)


def set_target(ticker: str, buy_price: float, note: str = "") -> None:
    targets = load_watch()
    targets[ticker] = {"buy_price": float(buy_price), "note": note}
    save_watch(targets)
