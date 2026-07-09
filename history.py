"""손익 추이(시계열) 재구성.

현재 보유 종목(수량·평균단가)을 과거 가격·환율에 대입해 포트폴리오 평가금액과
투자원금을 원화로 시계열 복원한다. 스냅샷이 쌓이길 기다릴 필요 없이 곧바로
손익 추이를 그릴 수 있다. (원금선은 매입가×수량을 각 시점 환율로 환산 —
평가선과 같은 환율을 써서 두 선의 간격이 '자산 가격 변동'을 반영하게 함.)
"""

from __future__ import annotations

from functools import lru_cache

import pandas as pd


@lru_cache(maxsize=64)
def _currency(ticker: str) -> str:
    import yfinance as yf
    try:
        return yf.Ticker(ticker).fast_info.currency or "USD"
    except Exception:
        return "USD"


def value_series(holdings: list[dict], period: str = "6mo") -> pd.DataFrame | None:
    """holdings: [{ticker, shares, avg_cost}] → 원화 평가금액/투자원금/손익 시계열."""
    import yfinance as yf

    items = [h for h in holdings
             if h.get("ticker") and h.get("shares") and h.get("avg_cost")]
    if not items:
        return None
    tickers = [h["ticker"] for h in items]

    px = yf.download(tickers, period=period, auto_adjust=True, progress=False)["Close"]
    if isinstance(px, pd.Series):
        px = px.to_frame(tickers[0])
    # 거래소별 휴장일 차이로 생기는 결측을 앞뒤로 채움(초반 값 왜곡 방지)
    px = px.dropna(how="all").ffill().bfill()
    if px.empty:
        return None

    currencies = {t: _currency(t) for t in tickers}
    fx_cache: dict[str, pd.Series] = {}
    for cur in set(currencies.values()):
        if cur == "KRW":
            fx_cache[cur] = pd.Series(1.0, index=px.index)
        else:
            try:
                f = yf.download(f"{cur}KRW=X", period=period,
                                auto_adjust=True, progress=False)["Close"]
                if isinstance(f, pd.DataFrame):
                    f = f.iloc[:, 0]
                fx_cache[cur] = f.reindex(px.index).ffill().bfill()
            except Exception:
                fx_cache[cur] = pd.Series(float("nan"), index=px.index)

    value = pd.Series(0.0, index=px.index)
    cost = pd.Series(0.0, index=px.index)
    for h in items:
        t = h["ticker"]
        if t not in px.columns:
            continue
        fx = fx_cache[currencies[t]]
        price = px[t].reindex(px.index).ffill()
        value = value.add(price * float(h["shares"]) * fx, fill_value=0)
        cost = cost.add(float(h["avg_cost"]) * float(h["shares"]) * fx, fill_value=0)

    df = pd.DataFrame({"평가금액": value, "투자원금": cost}).dropna()
    if df.empty:
        return None
    df["손익"] = df["평가금액"] - df["투자원금"]
    df["손익률(%)"] = (df["평가금액"] / df["투자원금"] - 1) * 100
    return df
