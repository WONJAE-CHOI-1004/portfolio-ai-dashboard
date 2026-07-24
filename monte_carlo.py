"""몬테카를로 VaR/CVaR + 매크로 베타 (참고용).

포트폴리오 일별수익률의 평균·분산(risk.returns_frame 재사용)을 정규분포로 근사해
벡터화된 몬테카를로 샘플링으로 VaR/CVaR을 계산한다. 하루 단위 경로를 순회하지
않고 지평(1일/1개월)에 맞춰 스케일링한 평균·표준편차에서 한 번에 표본을 뽑으므로
수만 회 시뮬레이션도 즉시 끝난다.

VaR 지평은 1일·1개월(21영업일) 두 가지를 기본으로 한다(1년 지평은 리스크
실무에서 잘 쓰이지 않아 제외 — 대신 wealth_fan_chart()가 1년 전망을 '참고용
시각화'로 별도 제공하며, 이는 예측이 아니라 일러스트레이션임을 UI에서 고지할 것).

환리스크 단순화: optimizer.py와 동일하게 각 종목의 자국통화 수익률을 KRW
평가금액 비중으로 가중한 근사치이며, 환율 자체의 변동성은 별도로 반영하지
않는다(기존 앱의 방법론과 일관성 유지).
"""

from __future__ import annotations

import numpy as np

import risk

TRADING_DAYS = 252
HORIZONS = {"1일": 1, "1개월": 21}
MACRO_TICKERS = {"미국채10년(^TNX)": "^TNX", "원달러환율(USDKRW=X)": "USDKRW=X"}


def _portfolio_weights(tickers: list[str], krw_values: dict[str, float] | None) -> np.ndarray:
    n = len(tickers)
    if not krw_values:
        return np.ones(n) / n
    w = np.array([max(krw_values.get(t, 0.0), 0.0) for t in tickers], dtype=float)
    return w / w.sum() if w.sum() > 0 else np.ones(n) / n


def _resolve_weights(cols: list[str], weights: list[float] | None,
                     krw_values: dict[str, float] | None) -> np.ndarray:
    if weights is not None and len(weights) == len(cols):
        w = np.array(weights, dtype=float)
        return w / w.sum() if w.sum() > 0 else np.ones(len(cols)) / len(cols)
    return _portfolio_weights(cols, krw_values)


def var_cvar(tickers: list[str], weights: list[float] | None = None,
            krw_values: dict[str, float] | None = None, period: str = "1y",
            n_sims: int = 10000, confidence: float = 0.95) -> dict | None:
    """포트폴리오 VaR/CVaR을 1일·1개월 지평으로 계산.

    weights를 직접 주지 않으면 krw_values(원화 평가금액)로 비중을 구성하고,
    그것도 없으면 동일가중을 쓴다.
    """
    rets = risk.returns_frame(tickers, period)
    if rets is None:
        return None
    cols = list(rets.columns)
    w = _resolve_weights(cols, weights, krw_values)

    daily = rets.values @ w  # 일별 포트폴리오 수익률 시계열
    mu_d, sigma_d = float(daily.mean()), float(daily.std(ddof=0))

    out = {"tickers": cols, "weights": {t: round(float(x), 4) for t, x in zip(cols, w)},
          "n_obs": int(rets.shape[0]), "n_sims": n_sims, "confidence": confidence,
          "horizons": {}}
    for label, h in HORIZONS.items():
        mu_h, sigma_h = mu_d * h, sigma_d * (h ** 0.5)
        sims = np.random.normal(mu_h, sigma_h, size=n_sims)  # 벡터화(일자별 루프 없음)
        alpha = 1 - confidence
        var_ret = float(np.percentile(sims, alpha * 100))
        cvar_ret = float(sims[sims <= var_ret].mean()) if (sims <= var_ret).any() else var_ret
        out["horizons"][label] = {
            "var_pct": round(-var_ret * 100, 2),   # 손실률로 부호 반전, %
            "cvar_pct": round(-cvar_ret * 100, 2),
            "mean_pct": round(mu_h * 100, 2),
        }
    return out


def wealth_fan_chart(tickers: list[str], weights: list[float] | None = None,
                     krw_values: dict[str, float] | None = None, period: str = "1y",
                     n_paths: int = 300, days: int = TRADING_DAYS) -> dict | None:
    """1년(기본) 전망 팬차트 — VaR과 달리 '참고용 시각화'다. 예측이 아니라
    현재까지의 변동성·평균수익률을 그대로 이어붙인 일러스트레이션이므로,
    호출부(UI)에서 반드시 그 취지를 고지할 것."""
    rets = risk.returns_frame(tickers, period)
    if rets is None:
        return None
    cols = list(rets.columns)
    w = _resolve_weights(cols, weights, krw_values)
    daily = rets.values @ w
    mu_d, sigma_d = float(daily.mean()), float(daily.std(ddof=0))

    draws = np.random.normal(mu_d, sigma_d, size=(n_paths, days))  # 벡터화, 일자 루프 없음
    cum = np.cumprod(1 + draws, axis=1)  # 누적 성장배수 경로
    pct = np.percentile(cum, [5, 25, 50, 75, 95], axis=0)
    return {
        "days": days, "n_paths": n_paths,
        "p5": pct[0].tolist(), "p25": pct[1].tolist(), "p50": pct[2].tolist(),
        "p75": pct[3].tolist(), "p95": pct[4].tolist(),
    }


def macro_beta(tickers: list[str], weights: list[float] | None = None,
              krw_values: dict[str, float] | None = None, period: str = "1y") -> dict | None:
    """포트폴리오의 매크로 팩터(10년물 금리, 원달러환율) 대비 롤링 베타."""
    import yfinance as yf
    rets = risk.returns_frame(tickers, period)
    if rets is None:
        return None
    cols = list(rets.columns)
    w = _resolve_weights(cols, weights, krw_values)

    out: dict[str, float | None] = {}
    for label, mticker in MACRO_TICKERS.items():
        try:
            fpx = yf.download(mticker, period=period, auto_adjust=True, progress=False)["Close"]
            if hasattr(fpx, "columns"):
                fpx = fpx.iloc[:, 0]
            factor_ret = fpx.pct_change().dropna()
        except Exception:  # noqa: BLE001
            out[label] = None
            continue
        common_idx = rets.index.intersection(factor_ret.index)
        if len(common_idx) < 30:
            out[label] = None
            continue
        p = rets.loc[common_idx].values @ w
        f = factor_ret.loc[common_idx].values
        var_f = float(np.var(f))
        beta = float(np.cov(p, f)[0, 1] / var_f) if var_f > 0 else None
        out[label] = round(beta, 2) if beta is not None else None
    return out
