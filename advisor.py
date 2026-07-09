"""약점 진단 → 보완 후보(섹터/자산) 추천 + 기대효과 시뮬레이션.

LLM이 티커를 지어내는 걸 막기 위해, 검증된 유동성 ETF 유니버스를 후보로 두고
'실제 데이터로' 편입 효과를 계산한 뒤 상위 후보를 고른다. LLM은 그 수치를
근거로 '왜 이 자산이 약점을 메우는지'를 한국어로 설명한다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import common
import optimizer
import risk

# 후보 유니버스: 섹터·지역·자산군을 폭넓게 대표하는 유동성 ETF
CANDIDATES: dict[str, tuple[str, str]] = {
    "QQQ": ("미국 기술주(나스닥100)", "성장/기술"),
    "XLV": ("미국 헬스케어", "방어/헬스케어"),
    "XLP": ("미국 필수소비재", "방어/소비"),
    "XLF": ("미국 금융", "경기/금융"),
    "XLU": ("미국 유틸리티", "방어/배당"),
    "VEA": ("선진국(미국 외) 주식", "지역분산"),
    "VWO": ("신흥국 주식", "지역분산/성장"),
    "EWJ": ("일본 주식", "지역분산"),
    "IEF": ("미국 중기국채(7-10년)", "안전자산/금리"),
    "TLT": ("미국 장기국채(20년+)", "안전자산/금리"),
    "TIP": ("미국 물가연동국채", "인플레이션 헤지"),
    "LQD": ("미국 투자등급 회사채", "인컴/신용"),
    "HYG": ("미국 하이일드 채권", "인컴/위험선호"),
    "VNQ": ("미국 리츠(부동산)", "실물/인컴"),
    "USMV": ("미국 최소변동성 주식", "저변동"),
    "DBC": ("광범위 원자재", "실물/인플레이션"),
}


def _effective_bets(rets: pd.DataFrame) -> float:
    corr = rets.corr().values
    eig = np.clip(np.linalg.eigvalsh(corr), 1e-12, None)
    p = eig / eig.sum()
    return float(np.exp(-(p * np.log(p)).sum()))


def _min_var_vol(rets: pd.DataFrame) -> float:
    cov = rets.cov().values * optimizer.TRADING_DAYS
    w = optimizer._min_variance(cov)
    return float(np.sqrt(w @ cov @ w))


def recommend(existing_tickers: list[str], period: str = "1y",
              top_k: int = 4) -> dict | None:
    """후보별 편입 효과를 시뮬레이션해 상위 top_k를 반환."""
    existing = [t for t in dict.fromkeys(existing_tickers) if t]
    if len(existing) < 2:
        return None
    cands = [c for c in CANDIDATES if c not in existing]
    all_tickers = existing + cands

    rets = risk.returns_frame(all_tickers, period)
    if rets is None:
        return None
    have = [t for t in existing if t in rets.columns]
    if len(have) < 2:
        return None

    base = rets[have]
    eb_before = _effective_bets(base)
    vol_before = _min_var_vol(base)
    w_equal_add = 1.0 / (len(have) + 1)  # 후보를 동일 비중 한 자리로 추가했다고 가정

    results = []
    for c in cands:
        if c not in rets.columns:
            continue
        sub = rets[have + [c]].dropna(how="any")
        if len(sub) < 30:
            continue
        cand_ret = sub[c]
        avg_corr = float(sub[have].corrwith(cand_ret).mean())
        eb_after = _effective_bets(sub)
        vol_after = _min_var_vol(sub)
        results.append({
            "ticker": c,
            "name": CANDIDATES[c][0],
            "category": CANDIDATES[c][1],
            "avg_corr": round(avg_corr, 2),
            "eff_bets_before": round(eb_before, 2),
            "eff_bets_after": round(eb_after, 2),
            "eff_bets_gain": round(eb_after - eb_before, 2),
            "minvar_vol_before": round(vol_before * 100, 1),
            "minvar_vol_after": round(vol_after * 100, 1),
            "minvar_vol_delta": round((vol_after - vol_before) * 100, 1),
        })

    # 정렬: 최소분산 변동성을 더 낮추고(음수), 평균상관이 낮은 순
    results.sort(key=lambda r: (r["minvar_vol_delta"], r["avg_corr"]))
    top = results[:top_k]
    return {
        "period": period,
        "existing": have,
        "eff_bets_before": round(eb_before, 2),
        "minvar_vol_before": round(vol_before * 100, 1),
        "candidates": top,
        "all_ranked": results,
    }


def explain(portfolio_desc: str, diag_text: str, rec: dict) -> str:
    """추천 결과(수치)를 근거로 약점 진단과 보완 효과를 한국어로 서술."""
    if not rec or not rec.get("candidates"):
        return ""
    cand_lines = []
    for c in rec["candidates"]:
        cand_lines.append(
            f"- {c['name']} ({c['ticker']}, {c['category']}): 기존과 평균상관 {c['avg_corr']}, "
            f"편입 시 유효베팅 {c['eff_bets_before']}→{c['eff_bets_after']}"
            f"(+{c['eff_bets_gain']}), 최소분산 변동성 {c['minvar_vol_before']}%"
            f"→{c['minvar_vol_after']}%({c['minvar_vol_delta']:+.1f}%p)")
    cand_block = "\n".join(cand_lines)

    prompt = f"""당신은 자산배분 애널리스트입니다. 아래는 한 개인 포트폴리오와 그 구조적 진단,
그리고 '검증된 후보 자산을 실제로 편입해 시뮬레이션한 결과'입니다. 투자 권유가 아니라 참고 분석입니다.

[현재 포트폴리오]
{portfolio_desc}

[구조 진단]
{diag_text}

[보완 후보 편입 시뮬레이션 결과]
{cand_block}

다음을 한국어로 작성하세요:
1) **약점 진단**: 이 포트폴리오가 구조적으로 부족한 부분(섹터·자산군·팩터·국면 노출)을 2~3가지로 짚기
2) **보완 추천**: 위 후보 중 약점을 가장 잘 메우는 것을 1~2개 고르고, 왜 적합한지 시뮬레이션 수치(상관·유효베팅·변동성 변화)를 인용해 설명
3) **기대효과**: 편입 시 포트폴리오가 어떻게 개선되는지(분산·변동성·국면 대응) 구체적으로
마지막 줄에 '⚠️ 참고용 분석이며 투자 판단·책임은 본인에게 있습니다.'"""
    try:
        return common.gemini(prompt, model=common.DEEP_MODEL, temperature=0.3)
    except Exception as e:  # noqa: BLE001
        return f"보완 추천 서술 실패: {e}"
