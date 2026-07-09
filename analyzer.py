"""분석 엔진: 빠른 요약(fast) / 심층(deep, TradingAgents) / 종목 간 시너지.

- fast_report : yfinance 스냅샷 → Gemini 1회 호출로 한국어 요약 리포트
- deep_report : 상위 폴더의 TradingAgents 애널리스트 토론 재사용
- synergy_report : 여러 종목 요약 + 상관계수 → 포트폴리오 시너지 서술
"""

from __future__ import annotations

import json

import common


RATING_ORDER = {"매수": 2, "비중확대": 2, "보유": 0, "중립": 0, "비중축소": -1, "매도": -2}


def _fmt_snapshot(snap: dict) -> str:
    t = snap.get("tech", {})
    lines = [
        f"종목: {snap['name']} ({snap['ticker']}), 통화 {snap['currency']}",
        f"섹터/산업: {snap.get('sector','?')} / {snap.get('industry','?')}",
        f"현재가: {snap.get('price')}",
        f"시가총액: {snap.get('market_cap')}",
        f"PER(TTM): {snap.get('pe')}, 선행PER: {snap.get('forward_pe')}",
        f"배당수익률: {snap.get('dividend_yield')}, 베타: {snap.get('beta')}",
        f"기술: 50일선 {t.get('sma50')}, 200일선 {t.get('sma200')}, "
        f"RSI14 {t.get('rsi14')}, 52주 {t.get('lo_52w')}~{t.get('hi_52w')}",
        f"수익률: 1개월 {t.get('chg_1m')}%, 3개월 {t.get('chg_3m')}%, 1년 {t.get('chg_1y')}%",
    ]
    if snap.get("summary"):
        lines.append(f"사업개요: {snap['summary']}")
    if snap.get("news"):
        lines.append("최근 뉴스 헤드라인:\n- " + "\n- ".join(snap["news"]))
    return "\n".join(lines)


def fast_report(snap: dict) -> dict:
    """스냅샷 1개 → 한국어 요약 리포트(dict)."""
    prompt = f"""당신은 신중한 주식 애널리스트입니다. 아래 데이터만 근거로 이 종목을 평가하세요.
투자 권유가 아니라 참고용 분석입니다. 반드시 한국어로, 아래 JSON 스키마로만 답하세요.

[데이터]
{_fmt_snapshot(snap)}

[출력 JSON 스키마]
{{
  "rating": "매수|보유|매도 중 하나",
  "headline": "한 줄 핵심 요약 (40자 내외)",
  "bull": ["강세 요인 2~3개(각 한 문장)"],
  "bear": ["약세/리스크 요인 2~3개(각 한 문장)"],
  "comment": "종합 코멘트 2~3문장(밸류에이션·기술적 위치·모멘텀 종합)",
  "watch": "앞으로 주목할 지표나 이벤트 한 문장"
}}"""
    try:
        data = common.gemini_json(prompt, model=common.QUICK_MODEL)
    except Exception as e:  # noqa: BLE001
        return {"rating": "분석실패", "headline": f"AI 요약 실패: {e}",
                "bull": [], "bear": [], "comment": "", "watch": "", "error": str(e)}
    # 방어적 정규화
    for k in ("bull", "bear"):
        v = data.get(k)
        if isinstance(v, str):
            data[k] = [v]
        elif not isinstance(v, list):
            data[k] = []
    data.setdefault("rating", "보유")
    data.setdefault("headline", "")
    data.setdefault("comment", "")
    data.setdefault("watch", "")
    return data


def deep_report(ticker: str, trade_date: str) -> dict:
    """상위 폴더의 TradingAgents 애널리스트 토론 실행 → {rating, reasoning}."""
    from executor import extract_rating  # 상위 폴더 (common이 sys.path에 추가)
    from run_analysis import _extract_reasoning
    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    config = DEFAULT_CONFIG.copy()  # 해외 종목 → 뉴스는 yfinance 기본값
    graph = TradingAgentsGraph(debug=False, config=config)
    final_state, decision = graph.propagate(ticker, trade_date)
    return {
        "rating": extract_rating(decision) or "HOLD",
        "reasoning": _extract_reasoning(final_state),
        "decision": decision,
    }


def synergy_report(reports: list[dict], corr_text: str = "", diag_text: str = "") -> str:
    """여러 종목 요약 + 상관계수 + 다중공선성 진단 → 포트폴리오 분석(한국어)."""
    if len(reports) < 2:
        return "종목이 2개 이상일 때 시너지 분석이 제공됩니다."
    lines = []
    for r in reports:
        s = r.get("snap", {})
        f = r.get("fast", {})
        lines.append(
            f"- {s.get('name')} ({s.get('ticker')}): 섹터 {s.get('sector','?')}, "
            f"통화 {s.get('currency')}, AI의견 {f.get('rating','?')}, "
            f"요지 {f.get('headline','')}")
    portfolio_block = "\n".join(lines)
    corr_block = f"\n\n[일간 수익률 상관계수]\n{corr_text}" if corr_text else ""
    diag_block = f"\n\n[다중공선성·분산 진단]\n{diag_text}" if diag_text else ""

    prompt = f"""아래는 한 개인 투자자가 함께 보유/관심 중인 종목들의 요약입니다.
이들을 하나의 포트폴리오로 볼 때의 '종목 간 시너지와 구조적 위험'을 한국어로 분석하세요.
투자 권유가 아니라 구조적 참고 분석입니다.

[구성 종목]
{portfolio_block}{corr_block}{diag_block}

다음을 포함해 6~8문장으로 서술하세요:
1) 섹터·테마·매크로 팩터(금리·에너지·원자재·안전자산 등)로 본 겹침과 보완 관계
2) 상관계수로 본 분산효과 — 서로 헤지되는 쌍과 같이 움직이는 쌍
3) **다중공선성 관점**: VIF·조건지수·유효 베팅 수를 근거로, 겉보기 상관은 낮아도 전체가 소수 공통 요인에 얽혀 있는지, 실질 분산이 종목 수만큼 되는지 해석
4) 통화 노출(USD/EUR/JPY 등)의 분산 또는 쏠림
5) 전체적으로 어떤 국면(위험선호/위험회피)에 유리한 조합인지, 구조적 쏠림 리스크는 무엇인지
지표 수치를 인용해 근거를 밝히세요. 마지막 줄에 '⚠️ 참고용 분석이며 투자 판단·책임은 본인에게 있습니다.'를 넣으세요."""
    try:
        return common.gemini(prompt, model=common.DEEP_MODEL, temperature=0.3)
    except Exception as e:  # noqa: BLE001
        return f"시너지 분석 실패: {e}"


def corr_to_text(corr) -> str:
    """상관계수 DataFrame → 프롬프트용 텍스트."""
    if corr is None:
        return ""
    try:
        return corr.to_string()
    except Exception:
        return ""
