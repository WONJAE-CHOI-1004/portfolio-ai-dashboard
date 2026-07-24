"""배당 캘린더 + 배당재투자(DRIP) 프로젝션 (참고용).

과거 배당 지급 이력(yfinance `tk.dividends`)으로 최근 12개월 실제 수령 패턴을
월별로 집계한다. 확정된 미래 일정이 아니라 '과거 지급월 패턴'이며, 회사가
배당 시기·빈도를 바꾸면 달라질 수 있다.

DRIP(배당재투자) 계산은 **주가·배당수익률이 그대로 유지된다는 보수적 가정**으로
재투자 시 늘어나는 주식 수만 계산한다(가격 성장률을 가정하지 않음 — 수익률 예측처럼
보이는 것을 피하기 위해 이 앱 전체의 '참고용' 원칙을 따름).
"""

from __future__ import annotations

import pandas as pd

import common

MONTH_LABELS = [f"{m}월" for m in range(1, 13)]


def _ticker_dividends(ticker: str) -> pd.Series | None:
    import yfinance as yf
    try:
        d = yf.Ticker(ticker).dividends
        return d if d is not None and not d.empty else None
    except Exception:  # noqa: BLE001
        return None


def _trailing_12m(div: pd.Series) -> pd.Series:
    """최근 12개월(366일) 이내 지급분만 남긴다. 인덱스가 타임존을 갖고 있으므로
    비교 기준 시각도 같은 타임존으로 맞춘다."""
    if div.empty:
        return div
    now = pd.Timestamp.now(tz=div.index.tz)
    return div[div.index >= now - pd.Timedelta(days=366)]


def analyze_portfolio(holdings: list[dict], snapshots: dict[str, dict] | None = None) -> dict:
    """holdings: [{ticker, shares, ...}]. snapshots: {ticker: snapshot_dict}(선택,
    파이프라인이 이미 가져온 dividend_yield·통화를 재사용해 중복 조회를 피함).

    반환: {rows, monthly_krw(1~12월 합계), total_annual_krw, has_data}
    """
    snapshots = snapshots or {}
    rows: list[dict] = []
    monthly_krw = {m: 0.0 for m in range(1, 13)}

    for h in holdings:
        ticker = (h.get("ticker") or "").strip()
        shares = h.get("shares")
        if not ticker or not shares:
            continue
        try:
            shares = float(shares)
        except (TypeError, ValueError):
            continue

        snap = snapshots.get(ticker)
        if snap:
            currency = snap.get("currency") or "USD"
            div_yield = snap.get("dividend_yield")
        else:
            import yfinance as yf
            try:
                fi = yf.Ticker(ticker).fast_info
                currency = getattr(fi, "currency", None) or "USD"
            except Exception:  # noqa: BLE001
                currency = "USD"
            try:
                div_yield = yf.Ticker(ticker).get_info().get("dividendYield")
            except Exception:  # noqa: BLE001
                div_yield = None

        fx = common.fx_to_krw(currency) or 1.0
        div = _ticker_dividends(ticker)
        if div is None:
            rows.append({"ticker": ticker, "has_history": False,
                        "currency": currency, "dividend_yield_pct": div_yield})
            continue

        recent = _trailing_12m(div)
        annual_per_share = float(recent.sum()) if len(recent) else 0.0
        annual_krw = annual_per_share * shares * fx

        by_month: dict[int, float] = {}
        for ts, amt in recent.items():
            m = ts.month
            by_month[m] = by_month.get(m, 0.0) + float(amt) * shares * fx
        for m, krw in by_month.items():
            monthly_krw[m] += krw

        rows.append({
            "ticker": ticker, "has_history": annual_per_share > 0,
            "currency": currency, "dividend_yield_pct": div_yield,
            "annual_dividend_per_share": round(annual_per_share, 4),
            "annual_dividend_krw": round(annual_krw, 0),
            "n_payments_12m": int(len(recent)),
        })

    total_annual_krw = sum(r.get("annual_dividend_krw", 0) for r in rows)
    return {
        "rows": rows,
        "monthly_krw": {MONTH_LABELS[m - 1]: round(v, 0) for m, v in monthly_krw.items()},
        "total_annual_krw": round(total_annual_krw, 0),
        "has_data": total_annual_krw > 0,
    }


def drip_projection(annual_dividend_krw: float, dividend_yield_pct: float | None,
                    years: int = 10) -> list[dict]:
    """배당재투자(DRIP) 보수적 프로젝션 — 주가·배당수익률 고정 가정.

    가격 상승을 전혀 가정하지 않고, 매년 배당수익률만큼 재투자해 늘어나는
    '주식 수 배수'만 계산한다. 투자 수익률 예측이 아니라 재투자 효과만 보여주는
    참고용 수치다.
    """
    if not dividend_yield_pct or dividend_yield_pct <= 0 or annual_dividend_krw <= 0:
        return []
    yield_frac = dividend_yield_pct / 100.0
    out = []
    shares_mult = 1.0
    for y in range(1, years + 1):
        shares_mult *= (1 + yield_frac)
        out.append({
            "year": y,
            "shares_multiplier": round(shares_mult, 4),
            "annual_dividend_krw_at_current_price": round(annual_dividend_krw * shares_mult, 0),
        })
    return out
