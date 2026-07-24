"""포트폴리오 분석 파이프라인 (대시보드 · 주간 스케줄 공용).

run_portfolio(holdings, date) → 종목별 빠른 리포트 + 손익 + 상관계수 + 시너지
전체를 담은 JSON 직렬화 가능한 dict 반환.

수집은 2단계로 나뉜다:
  1) 병렬(ThreadPoolExecutor) — yfinance 시세·밸류에이션만 수집(I/O bound, 스레드 세이프)
  2) 순차 — Gemini AI 리포트 생성(LLM bound). common.gemini()의 429 재시도/폴백 로직이
     스레드 세이프하지 않고 무료 한도가 빠듯하므로 이 단계는 병렬화하지 않는다.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

import common
import analyzer
import risk
import optimizer
import valuation

LATEST_PATH = os.path.join(common.CACHE_DIR, "latest.json")
MAX_WORKERS = 5  # yfinance 과다 동시요청으로 인한 차단 방지


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _fetch_stock_data(ticker: str) -> dict:
    """스레드풀 워커: 종목 1개의 시세 스냅샷 + 밸류에이션을 함께 가져온다.
    yfinance 호출만 수행하므로 스레드 세이프하다(LLM 호출 없음)."""
    snap = common.snapshot(ticker)
    try:
        val = valuation.fair_value(ticker)
    except Exception:  # noqa: BLE001
        val = None
    return {"snap": snap, "valuation": val}


def run_portfolio(holdings: list[dict], trade_date: str | None = None,
                  progress: Callable[[float, str], None] | None = None,
                  with_synergy: bool = True) -> dict:
    """holdings: [{query, ticker(optional), shares(optional), avg_cost(optional)}]"""
    trade_date = trade_date or dt.date.today().isoformat()
    holdings = [h for h in holdings if (h.get("query") or h.get("ticker"))]
    n = len(holdings)

    def report(frac, msg):
        if progress:
            progress(frac, msg)

    # 0) 티커 해석 (순차, 이름검색 1회라 저렴). 입력 순서를 유지하기 위해
    #    인덱스를 키로 두 딕셔너리(해석 성공/실패)에 나눠 담고 마지막에 순서대로 조립한다.
    resolved: dict[int, tuple[dict, str, str]] = {}
    stocks_by_idx: dict[int, dict] = {}
    for idx, h in enumerate(holdings):
        report(0.02 + 0.03 * (idx / max(n, 1)), f"티커 확인 중 ({idx + 1}/{n})")
        query = (h.get("query") or "").strip()
        ticker = (h.get("ticker") or "").strip()
        if not ticker:
            ticker = common.best_ticker(query) or ""
        if not ticker:
            stocks_by_idx[idx] = {"query": query, "ticker": "", "error": "티커를 찾지 못함",
                                  "name": query, "fast": {"rating": "미해결",
                                  "headline": "종목을 찾지 못했어요. 티커를 직접 입력해 주세요."}}
            continue
        resolved[idx] = (h, query, ticker)

    # 1) 병렬 시세 수집 (yfinance I/O만)
    total = len(resolved)
    fetched: dict[int, dict] = {}
    if resolved:
        report(0.05, f"시세 수집 중... (0/{total})")
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futures = {ex.submit(_fetch_stock_data, ticker): idx
                       for idx, (_, _, ticker) in resolved.items()}
            done = 0
            for fut in as_completed(futures):
                idx = futures[fut]
                try:
                    fetched[idx] = fut.result()
                except Exception as e:  # noqa: BLE001
                    fetched[idx] = {"snap": None, "valuation": None, "error": str(e)}
                done += 1
                report(0.05 + 0.45 * (done / total), f"시세 수집 완료 ({done}/{total})")

    # 2) 순차 AI 리포트 (Gemini) — 입력 순서대로
    for i, (idx, (h, query, ticker)) in enumerate(resolved.items()):
        report(0.5 + 0.3 * (i / max(total, 1)), f"AI 분석 중: {ticker}")
        fd = fetched.get(idx) or {}
        snap = fd.get("snap") or {"ticker": ticker, "name": query or ticker,
                                   "price": None, "currency": "USD", "tech": {}, "news": []}
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
            "valuation": fd.get("valuation"),
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
        stocks_by_idx[idx] = row

    stocks = [stocks_by_idx[i] for i in sorted(stocks_by_idx)]

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
