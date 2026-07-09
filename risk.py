"""포트폴리오 다중공선성 · 분산 진단.

쌍별 상관계수만으로는 '전체가 하나의 요인에 얽혀 있는' 공선성을 못 잡는다.
아래 금융/통계 표준 지표로 포트폴리오 전체의 중복 위험을 진단한다.

- VIF(분산팽창계수): 각 종목을 나머지 종목들로 회귀했을 때의 중복도
- 조건지수(Condition Index, Belsley): 상관행렬 전체 공선성 심각도
- 유효 베팅 수(Effective Number of Bets, PCA 엔트로피): 실질 독립 베팅 개수
- 상관행렬 행렬식: 1=직교, 0=완전 공선
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def returns_frame(tickers: list[str], period: str = "1y") -> pd.DataFrame | None:
    """공통 거래일에 정렬된 일간 수익률 행렬(T×N)."""
    import yfinance as yf
    tickers = [t for t in dict.fromkeys(tickers) if t]  # 중복·빈값 제거, 순서 유지
    if len(tickers) < 2:
        return None
    try:
        px = yf.download(tickers, period=period, auto_adjust=True, progress=False)["Close"]
        if isinstance(px, pd.Series):
            return None
        px = px[tickers] if set(tickers).issubset(px.columns) else px
        rets = px.pct_change().dropna(how="any")
        return rets if len(rets) > len(tickers) + 5 else rets
    except Exception:
        return None


def _vif(rets: pd.DataFrame) -> dict[str, float]:
    """각 종목의 VIF = 1/(1-R²). R²는 그 종목을 나머지로 회귀한 결정계수."""
    X = rets.values
    n = X.shape[1]
    out: dict[str, float] = {}
    for i, col in enumerate(rets.columns):
        y = X[:, i]
        others = np.delete(X, i, axis=1)
        A = np.column_stack([np.ones(len(others)), others])  # 상수항 포함
        # 최소자승 회귀 → R²
        coef, _, _, _ = np.linalg.lstsq(A, y, rcond=None)
        resid = y - A @ coef
        ss_res = float(resid @ resid)
        ss_tot = float(((y - y.mean()) ** 2).sum())
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
        r2 = min(max(r2, 0.0), 0.999999)
        out[col] = round(1.0 / (1.0 - r2), 2)
    return out


def diagnose(tickers: list[str], period: str = "1y") -> dict | None:
    """다중공선성/분산 진단 결과 dict. 데이터 부족 시 None."""
    rets = returns_frame(tickers, period)
    if rets is None or rets.shape[1] < 2:
        return None
    cols = list(rets.columns)
    n = len(cols)
    corr = rets.corr()
    C = corr.values

    # 고유값 분해 (상관행렬 → 대각합 = n)
    eig = np.linalg.eigvalsh(C)
    eig = np.clip(eig, 1e-12, None)[::-1]  # 내림차순, 음수 방지
    lam_max, lam_min = float(eig[0]), float(eig[-1])

    condition_index = float(np.sqrt(lam_max / lam_min))  # Belsley 조건지수
    determinant = float(np.linalg.det(C))

    # PCA: 분산 설명 비율 & 유효 베팅 수(엔트로피 기반)
    p = eig / eig.sum()
    entropy = float(-(p * np.log(p)).sum())
    effective_bets = float(np.exp(entropy))
    pc1_pct = float(eig[0] / n * 100)
    cum = np.cumsum(eig) / n
    n_for_90 = int(np.searchsorted(cum, 0.90) + 1)

    vif = _vif(rets)
    max_vif = max(vif.values())

    # 종합 판정
    flags = []
    if max_vif >= 10:
        flags.append("심각한 공선성(VIF≥10)")
    elif max_vif >= 5:
        flags.append("주의 수준 공선성(VIF≥5)")
    if condition_index >= 30:
        flags.append("조건지수 높음(≥30)")
    if effective_bets < n / 2:
        flags.append(f"유효 베팅 수 낮음({effective_bets:.1f}/{n})")
    if not flags:
        flags.append("전반적으로 양호")

    return {
        "tickers": cols,
        "n": n,
        "n_obs": int(rets.shape[0]),
        "period": period,
        "vif": vif,
        "max_vif": round(max_vif, 2),
        "condition_index": round(condition_index, 1),
        "determinant": round(determinant, 4),
        "effective_bets": round(effective_bets, 2),
        "pc1_pct": round(pc1_pct, 1),
        "n_for_90": n_for_90,
        "eigenvalues": [round(float(e), 3) for e in eig],
        "flags": flags,
    }


def to_text(diag: dict) -> str:
    """AI 프롬프트/로그용 요약 텍스트."""
    if not diag:
        return ""
    vif_str = ", ".join(f"{k} {v}" for k, v in diag["vif"].items())
    return (
        f"관측일수 {diag['n_obs']}, 종목수 {diag['n']}\n"
        f"VIF: {vif_str} (최대 {diag['max_vif']})\n"
        f"조건지수(Condition Index): {diag['condition_index']} (>30이면 강한 공선성)\n"
        f"상관행렬 행렬식: {diag['determinant']} (0에 가까울수록 공선)\n"
        f"유효 베팅 수: {diag['effective_bets']} / {diag['n']} "
        f"(PC1이 전체 분산의 {diag['pc1_pct']}% 설명, 90% 설명에 {diag['n_for_90']}개 성분 필요)\n"
        f"판정: {', '.join(diag['flags'])}"
    )
