"""포트폴리오 재구성(최적화) + 과거 시뮬레이션(백테스트).

수익률 예측은 불안정하므로, 수익률 추정이 필요 없는 견고한 방식 위주로 제시한다.
- 동일가중(equal), 현재비중(current)
- 최소분산(min-variance): 변동성 최소
- 리스크패리티(risk-parity): 각 종목이 위험에 동등하게 기여

각 비중안을 지난 1년 일간수익률로 백테스트해 연율 수익률/변동성/샤프/최대낙폭/
분산비율을 비교한다. (과거 성과이며 미래를 보장하지 않음.)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import minimize

import risk

TRADING_DAYS = 252


def _annualized(daily: pd.Series) -> dict:
    r = daily.dropna()
    if len(r) < 20:
        return {}
    ann_ret = float(r.mean() * TRADING_DAYS)
    ann_vol = float(r.std(ddof=0) * np.sqrt(TRADING_DAYS))
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0.0
    curve = (1 + r).cumprod()
    mdd = float((curve / curve.cummax() - 1).min())
    return {"ann_return": ann_ret, "ann_vol": ann_vol,
            "sharpe": sharpe, "mdd": mdd}


def _diversification_ratio(w: np.ndarray, cov: np.ndarray) -> float:
    port_vol = float(np.sqrt(w @ cov @ w))
    if port_vol <= 0:
        return 1.0
    weighted_vol = float(w @ np.sqrt(np.diag(cov)))
    return weighted_vol / port_vol


def _min_variance(cov: np.ndarray) -> np.ndarray:
    n = len(cov)
    w0 = np.ones(n) / n
    cons = ({"type": "eq", "fun": lambda w: w.sum() - 1},)
    bnds = tuple((0.0, 1.0) for _ in range(n))
    res = minimize(lambda w: w @ cov @ w, w0, method="SLSQP",
                   bounds=bnds, constraints=cons)
    s = res.x.sum()
    return res.x / s if s > 0 else w0  # 미수렴(합=0) 시 동일가중 폴백


def _risk_parity(cov: np.ndarray) -> np.ndarray:
    n = len(cov)
    w0 = np.ones(n) / n

    def obj(w):
        port_var = w @ cov @ w
        rc = w * (cov @ w)              # 각 종목 위험기여
        target = port_var / n
        return float(((rc - target) ** 2).sum())

    cons = ({"type": "eq", "fun": lambda w: w.sum() - 1},)
    bnds = tuple((1e-4, 1.0) for _ in range(n))
    res = minimize(obj, w0, method="SLSQP", bounds=bnds, constraints=cons)
    s = res.x.sum()
    return res.x / s if s > 0 else w0  # 미수렴(합=0) 시 동일가중 폴백


def rebalance(tickers: list[str], current_weights: dict[str, float] | None = None,
              period: str = "1y") -> dict | None:
    """여러 비중안을 계산하고 백테스트 비교표를 만든다."""
    rets = risk.returns_frame(tickers, period)
    if rets is None or rets.shape[1] < 2:
        return None
    cols = list(rets.columns)
    n = len(cols)
    cov = rets.cov().values * TRADING_DAYS  # 연율 공분산
    R = rets.values

    schemes: dict[str, np.ndarray] = {}
    schemes["동일가중"] = np.ones(n) / n
    if current_weights:
        cw = np.array([max(current_weights.get(c, 0.0), 0.0) for c in cols], float)
        if cw.sum() > 0:
            schemes["현재비중"] = cw / cw.sum()
    schemes["최소분산"] = _min_variance(cov)
    schemes["리스크패리티"] = _risk_parity(cov)

    rows = []
    weights_out = {}
    for name, w in schemes.items():
        daily = pd.Series(R @ w, index=rets.index)
        stats = _annualized(daily)
        stats["dr"] = _diversification_ratio(w, cov)
        rows.append({
            "구성안": name,
            "연율수익률": round(stats.get("ann_return", 0) * 100, 1),
            "연율변동성": round(stats.get("ann_vol", 0) * 100, 1),
            "샤프": round(stats.get("sharpe", 0), 2),
            "최대낙폭": round(stats.get("mdd", 0) * 100, 1),
            "분산비율": round(stats["dr"], 2),
        })
        weights_out[name] = {c: round(float(wi) * 100, 1) for c, wi in zip(cols, w)}

    return {
        "tickers": cols,
        "period": period,
        "n_obs": int(rets.shape[0]),
        "table": rows,
        "weights": weights_out,
    }
