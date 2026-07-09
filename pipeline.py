"""포트폴리오 분석 파이프라인 (대시보드 · 주간 스케줄 공용).

run_portfolio(holdings, date) → 종목별 빠른 리포트 + 손익 + 상관계수 + 시너지
전체를 담은 JSON 직렬화 가능한 dict 반환.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from typing import Callable

import common
import analyzer
import risk
import optimizer
import valuation

LATEST_PATH = os.path.join(common.CACHE_DIR, "latest.json")


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def run_portfolio(holdings: list[dict], trade_date: str | None = None,
                  progress: Callable[[float, str], None] | None = None,
                  with_synergy: bool = True) -> dict:
    """holdings: [{query, ticker(optional), shares(optional), avg_cost(optional)}]"""
    trade_date = trade_date or dt.date.today().isoformat()
    holdings = [h for h in holdings if (h.get("query") or h.get("ticker"))]
    n = len(holdings)
    stocks: list[dict] = []

    def report(frac, msg):
        if progress:
            progress(frac, msg)

    for i, h in enumerate(holdings):
        base = 0.05 + 0.75 * (i / max(n, 1))
        query = (h.get("query") or "").strip()
        ticker = (h.get("ticker") or "").strip()
        if not ticker:
            report(base, f"티커 찾는 중: {query}")
            ticker = common.best_ticker(query) or ""
        if not ticker:
            stocks.append({"query": query, "ticker": "", "error": "티커를 찾지 못함",
                           "name": query, "fast": {"rating": "미해결",
                           "headline": "종목을 찾지 못했어요. 티커를 직접 입력해 주세요."}})
            continue

        report(base, f"분석 중: {ticker}")
        snap = common.snapshot(ticker)
        fast = analyzer.fast_report(snap)

        shares = _num(h.get("shares"))
        avg_cost = _num(h.get("avg_cost"))
        price = snap.get("price")
        currency = snap.get("currency") or "USD"
        fx = common.fx_to_krw(currency)

        row = {
            "query": query or snap.get("name"),
            "ticker": ticker,
            "name": snap.get("name"),
            "currency": currency,
            "price": price,
            "sector": snap.get("sector"),
            "shares": shares,
            "avg_cost": avg_cost,
            "fx_krw": fx,
            "fast": fast,
            "snap": {k: snap.get(k) for k in
                     ("name", "ticker", "sector", "industry", "currency", "price",
                      "pe", "forward_pe", "dividend_yield", "beta", "tech", "news")},
        }
        if shares and avg_cost and price:
            mv = price * shares
            cost = avg_cost * shares
            row.update({
                "market_value": mv, "cost_value": cost,
                "pnl": mv - cost,
                "pnl_pct": (price / avg_cost - 1) * 100 if avg_cost else None,
                "market_value_krw": mv * fx if fx else None,
                "pnl_krw": (mv - cost) * fx if fx else None,
                "cost_value_krw": cost * fx if fx else None,
            })
        stocks.append(row)

    # 포트폴리오 원화 합계
    cost_krw = sum(s["cost_value_krw"] for s in stocks if s.get("cost_value_krw"))
    mv_krw = sum(s["market_value_krw"] for s in stocks if s.get("market_value_krw"))
    totals = None
    if cost_krw:
        totals = {"cost_krw": cost_krw, "mv_krw": mv_krw,
                  "pnl_krw": mv_krw - cost_krw,
                  "pnl_pct": (mv_krw / cost_krw - 1) * 100}

    # 상관계수
    report(0.82, "상관계수 계산 중...")
    tickers = [s["ticker"] for s in stocks if s.get("ticker")]
    corr = common.correlation_matrix(tickers)
    corr_obj = None
    corr_text = ""
    if corr is not None:
        corr_obj = {"tickers": list(corr.columns),
                    "matrix": corr.values.tolist()}
        corr_text = analyzer.corr_to_text(corr)

    # 밸류에이션 · 적정 매수가 (종목별)
    report(0.8, "밸류에이션·적정가 계산 중...")
    for s in stocks:
        if s.get("ticker") and not s.get("error"):
            try:
                s["valuation"] = valuation.fair_value(s["ticker"])
            except Exception:  # noqa: BLE001
                s["valuation"] = None

    # 다중공선성 · 분산 진단
    report(0.85, "다중공선성 진단 중...")
    diag = risk.diagnose(tickers)
    diag_text = risk.to_text(diag) if diag else ""

    # 이상적 재구성 시뮬레이션 (현재 원화 평가금액 비중 기준)
    report(0.87, "재구성 시뮬레이션 중...")
    cw = {s["ticker"]: s.get("market_value_krw") for s in stocks
          if s.get("market_value_krw")}
    rebal = optimizer.rebalance(tickers, cw or None)

    # 시너지 (상관계수 + 공선성 진단을 함께 반영)
    synergy = ""
    if with_synergy:
        report(0.9, "종목 간 시너지 분석 중...")
        valid = [s for s in stocks if not s.get("error")]
        synergy = analyzer.synergy_report(valid, corr_text, diag_text)

    report(1.0, "완료")
    result = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "trade_date": trade_date,
        "stocks": stocks,
        "totals": totals,
        "correlation": corr_obj,
        "diagnostics": diag,
        "rebalance": rebal,
        "synergy": synergy,
    }
    return result


def save_latest(result: dict) -> str:
    with open(LATEST_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    return LATEST_PATH


def load_latest() -> dict | None:
    if not os.path.exists(LATEST_PATH):
        return None
    try:
        with open(LATEST_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None
