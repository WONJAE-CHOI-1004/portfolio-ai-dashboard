"""내 포트폴리오 AI 리포트 대시보드 (Streamlit).

- 종목명을 병렬로 입력 → 자동 티커 변환 → 종목별 빠른 AI 리포트 + 손익
- 종목 간 시너지(상관계수 + AI 서술)
- 원하는 종목만 '심층 분석'(TradingAgents 애널리스트 토론)
- 목록/수량 편집·저장, 주간 스케줄 결과도 같은 캐시를 사용
"""

from __future__ import annotations

import datetime as dt
import json
import os

import pandas as pd
import streamlit as st

import common
import pipeline
import analyzer
import emailer
import subscribers

HERE = os.path.dirname(os.path.abspath(__file__))
WATCHLIST_PATH = os.path.join(HERE, "watchlist.json")
DEEP_DIR = os.path.join(common.CACHE_DIR, "deep")
os.makedirs(DEEP_DIR, exist_ok=True)

st.set_page_config(page_title="내 포트폴리오 AI 리포트", page_icon="📈", layout="wide")

RATING_STYLE = {
    "매수": ("🟢", "#16a34a"), "비중확대": ("🟢", "#16a34a"),
    "보유": ("🟡", "#ca8a04"), "중립": ("🟡", "#ca8a04"),
    "매도": ("🔴", "#dc2626"), "비중축소": ("🔴", "#dc2626"),
    "BUY": ("🟢", "#16a34a"), "OVERWEIGHT": ("🟢", "#16a34a"),
    "HOLD": ("🟡", "#ca8a04"),
    "SELL": ("🔴", "#dc2626"), "UNDERWEIGHT": ("🔴", "#dc2626"),
}


# ── 목록 로딩/저장 ──────────────────────────────────────────────────
def load_watchlist() -> list[dict]:
    if os.path.exists(WATCHLIST_PATH):
        try:
            with open(WATCHLIST_PATH, encoding="utf-8") as f:
                return json.load(f).get("holdings", [])
        except Exception:
            pass
    return [{"query": "", "ticker": "", "shares": None, "avg_cost": None}]


def save_watchlist(rows: list[dict]) -> None:
    clean = [r for r in rows if (r.get("query") or r.get("ticker"))]
    with open(WATCHLIST_PATH, "w", encoding="utf-8") as f:
        json.dump({"holdings": clean}, f, ensure_ascii=False, indent=2)


def fmt(v, nd=2):
    return "-" if v is None else f"{v:,.{nd}f}"


# ── 헤더 ────────────────────────────────────────────────────────────
st.title("📈 내 포트폴리오 AI 리포트")
st.caption("종목명을 여러 개 입력하면 티커를 자동으로 찾아 AI 리포트와 종목 간 시너지를 만들어 드려요. "
           "⚠️ 참고용 분석이며 투자 판단·책임은 본인에게 있습니다.")

# ── 공개 영역: 구독 확인/해지(링크 클릭) + 구독 신청 ─────────────────
_ecfg = emailer.load_config()
_qp = st.query_params
if "confirm" in _qp:
    _ok, _em = subscribers.confirm(_qp["confirm"])
    st.success(f"✅ 구독이 확정되었습니다: {_em}") if _ok \
        else st.error("확인 링크가 유효하지 않거나 만료되었습니다.")
if "unsub" in _qp:
    _ok, _em = subscribers.unsubscribe(_qp["unsub"])
    st.info(f"수신거부되었습니다: {_em} — 더 이상 메일을 보내지 않아요.") if _ok \
        else st.error("수신거부 링크가 유효하지 않습니다.")

with st.expander("📬 리포트 이메일 구독하기",
                 expanded=("confirm" in _qp or "unsub" in _qp)):
    st.caption("이메일을 등록하면 확인 메일이 갑니다. 링크를 클릭해야 구독이 완료돼요(원클릭 수신거부 가능).")
    _sub_email = st.text_input("이메일 주소", key="sub_email")
    if st.button("구독 신청"):
        if not subscribers.valid_email(_sub_email):
            st.error("올바른 이메일 주소를 입력하세요.")
        elif not (_ecfg.get("sender") and _ecfg.get("app_password")):
            st.error("아직 발송 설정이 안 됐어요. (관리자 문의)")
        else:
            _state, _tok = subscribers.subscribe(_sub_email)
            if _state == "already":
                st.info("이미 구독 중인 이메일이에요.")
            else:
                _ok, _msg = subscribers.send_confirmation(
                    _sub_email, _tok, _ecfg.get("base_url", ""), _ecfg)
                st.success("확인 메일을 보냈어요! 편지함의 링크를 클릭하면 구독 완료됩니다.") if _ok \
                    else st.error(f"확인 메일 발송 실패: {_msg}")

# ── 소유자 인증 게이트 (owner_password 설정 시에만 작동; 로컬은 통과) ──
_owner_pw = _ecfg.get("owner_password", "")
if _owner_pw and not st.session_state.get("is_owner"):
    st.markdown("---")
    st.caption("🔒 아래 대시보드는 소유자 전용이에요. (방문자는 위 구독 기능만 이용 가능)")
    _pw_try = st.text_input("소유자 비밀번호", type="password", key="owner_pw_try")
    if st.button("로그인") and _pw_try:
        if _pw_try == _owner_pw:
            st.session_state.is_owner = True
            st.rerun()
        else:
            st.error("비밀번호가 틀렸습니다.")
    st.stop()

with st.sidebar:
    st.header("⚙️ 설정")
    trade_date = st.date_input("분석 기준일", value=dt.date.today()).isoformat()
    st.markdown("---")
    st.markdown("**분석 깊이**\n\n"
                "• 기본: ⚡빠른 요약 (종목당 수 초)\n\n"
                "• 원하는 종목만 🔬심층 분석 버튼으로 TradingAgents 실행")
    st.markdown("---")
    st.caption(f"빠른 모델: {common.QUICK_MODEL}\n\n심층 모델: {common.DEEP_MODEL}")
    latest = pipeline.load_latest()
    if latest:
        st.success(f"최근 분석: {latest.get('generated_at','?')}")


# ── 1) 종목 입력 ────────────────────────────────────────────────────
st.subheader("1️⃣ 종목 입력")
st.caption("종목명만 넣어도 돼요(예: 에퀴노르, apple). 티커를 알면 티커 칸에 직접 넣으면 정확해요. "
           "수량·평균단가를 넣으면 손익도 계산해요(선택).")

if "editor_df" not in st.session_state:
    st.session_state.editor_df = pd.DataFrame(load_watchlist())
    for col in ("query", "ticker", "shares", "avg_cost"):
        if col not in st.session_state.editor_df.columns:
            st.session_state.editor_df[col] = None

edited = st.data_editor(
    st.session_state.editor_df[["query", "ticker", "shares", "avg_cost"]],
    num_rows="dynamic", use_container_width=True, key="editor",
    column_config={
        "query": st.column_config.TextColumn("종목명", help="예: 에퀴노르, Heidelberg Materials, apple"),
        "ticker": st.column_config.TextColumn("티커(선택)", help="알면 직접 입력. 비우면 자동으로 찾음"),
        "shares": st.column_config.NumberColumn("수량", min_value=0.0, step=1.0),
        "avg_cost": st.column_config.NumberColumn("평균단가(현지통화)", min_value=0.0),
    },
)

c1, c2, c3 = st.columns([1, 1, 1])
with c1:
    do_resolve = st.button("🔎 티커 자동 확인", use_container_width=True)
with c2:
    do_run = st.button("⚡ 빠른 분석 실행", type="primary", use_container_width=True)
with c3:
    if st.button("💾 목록 저장", use_container_width=True):
        save_watchlist(edited.to_dict("records"))
        st.toast("목록을 저장했어요. 주간 스케줄도 이 목록을 사용해요.")

# 티커 자동 확인: 후보를 보여줌
if do_resolve:
    st.markdown("**티커 변환 결과**")
    for r in edited.to_dict("records"):
        q = (r.get("query") or "").strip()
        if not q and not r.get("ticker"):
            continue
        if r.get("ticker"):
            st.write(f"• `{r['ticker']}` (직접 입력): {q}")
            continue
        cands = common.resolve_ticker(q)
        if not cands:
            st.write(f"• ❓ **{q}** → 후보 없음. 티커를 직접 입력해 주세요.")
        else:
            top = cands[0]
            others = ", ".join(f"{c['symbol']}({c['exchange']})" for c in cands[1:4])
            st.write(f"• **{q}** → `{top['symbol']}` — {top['name']} [{top['exchange']}]"
                     + (f"  · 다른 후보: {others}" if others else ""))
    st.info("자동 선택이 원하는 상장(예: 도쿄/프랑크푸르트)과 다르면, 티커 칸에 직접 입력하세요.")

# 빠른 분석 실행
if do_run:
    save_watchlist(edited.to_dict("records"))
    holdings = edited.to_dict("records")
    bar = st.progress(0.0, text="시작...")
    try:
        result = pipeline.run_portfolio(
            holdings, trade_date,
            progress=lambda f, m: bar.progress(min(f, 1.0), text=m))
        pipeline.save_latest(result)
        st.session_state.result = result
        st.session_state.pop("deep_cache", None)
        bar.empty()
        st.toast("분석 완료!")
    except Exception as e:  # noqa: BLE001
        bar.empty()
        st.error(f"분석 중 오류: {e}")


# ── 2) 결과 표시 ────────────────────────────────────────────────────
result = st.session_state.get("result") or pipeline.load_latest()
if not result:
    st.info("위에서 종목을 입력하고 **⚡ 빠른 분석 실행**을 눌러보세요.")
    st.stop()

st.markdown("---")
st.subheader("2️⃣ 포트폴리오 요약")
st.caption(f"분석 시각: {result.get('generated_at','?')} · 기준일 {result.get('trade_date','?')}")

stocks = result["stocks"]

# 손익 요약 표
rows = []
for s in stocks:
    icon = RATING_STYLE.get(s["fast"].get("rating"), ("⚪", "#666"))[0]
    rows.append({
        "종목": f"{s.get('name','?')} ({s.get('ticker','')})",
        "AI의견": f"{icon} {s['fast'].get('rating','-')}",
        "현재가": f"{fmt(s.get('price'))} {s.get('currency','')}",
        "수량": fmt(s.get("shares"), 0) if s.get("shares") else "-",
        "손익률": (f"{s['pnl_pct']:+.1f}%" if s.get("pnl_pct") is not None else "-"),
        "원화손익": (f"{s['pnl_krw']:+,.0f}원" if s.get("pnl_krw") is not None else "-"),
    })
st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

totals = result.get("totals")
if totals:
    m1, m2, m3 = st.columns(3)
    m1.metric("평가금액(원화)", f"{totals['mv_krw']:,.0f}원")
    m2.metric("매입금액(원화)", f"{totals['cost_krw']:,.0f}원")
    m3.metric("총 손익", f"{totals['pnl_krw']:+,.0f}원", f"{totals['pnl_pct']:+.2f}%")

# 손익 추이 그래프 (현재 보유를 과거 가격·환율로 복원)
st.markdown("**📉 손익 추이** — 현재 보유 종목을 과거 시세·환율로 되짚은 평가금액 변화예요.")
_period = st.radio("기간", ["3mo", "6mo", "1y", "2y"], index=1,
                   horizontal=True, key="trend_period")


@st.cache_data(ttl=1800, show_spinner=False)
def _trend(holdings_key: tuple, period: str):
    import history
    holds = [{"ticker": t, "shares": sh, "avg_cost": ac}
             for t, sh, ac in holdings_key]
    return history.value_series(holds, period)


_hkey = tuple((s["ticker"], s.get("shares"), s.get("avg_cost"))
              for s in stocks if s.get("ticker") and s.get("shares") and s.get("avg_cost"))
if _hkey:
    with st.spinner("손익 추이 계산 중..."):
        try:
            tdf = _trend(_hkey, _period)
        except Exception as e:  # noqa: BLE001
            tdf = None
            st.caption(f"추이 계산 실패: {e}")
    if tdf is not None and not tdf.empty:
        gc = st.columns([3, 2])
        with gc[0]:
            st.caption("평가금액 vs 투자원금 (원화)")
            st.line_chart(tdf[["평가금액", "투자원금"]])
        with gc[1]:
            st.caption("손익률 추이 (%)")
            st.line_chart(tdf[["손익률(%)"]])
        cur = tdf.iloc[-1]
        st.caption(f"기간 최고 손익률 {tdf['손익률(%)'].max():+.1f}% · "
                   f"최저 {tdf['손익률(%)'].min():+.1f}% · 현재 {cur['손익률(%)']:+.1f}%")
else:
    st.caption("수량·평균단가가 입력된 종목이 있어야 손익 추이를 그려요.")


# ── 3) 종목별 리포트 ────────────────────────────────────────────────
st.markdown("---")
st.subheader("3️⃣ 종목별 AI 리포트")

deep_cache = st.session_state.setdefault("deep_cache", {})


def deep_path(ticker, date):
    return os.path.join(DEEP_DIR, f"{ticker.replace('.', '_')}_{date}.json")


for s in stocks:
    fast = s["fast"]
    icon, color = RATING_STYLE.get(fast.get("rating"), ("⚪", "#666"))
    header = f"{icon} {s.get('name','?')} ({s.get('ticker','')}) — {fast.get('rating','-')}"
    with st.expander(header, expanded=True):
        if s.get("error"):
            st.warning(s["error"])
            continue
        st.markdown(f"**{fast.get('headline','')}**")
        cc = st.columns([1, 1])
        with cc[0]:
            st.markdown("**👍 강세 요인**")
            for b in fast.get("bull", []):
                st.markdown(f"- {b}")
        with cc[1]:
            st.markdown("**👎 약세/리스크**")
            for b in fast.get("bear", []):
                st.markdown(f"- {b}")
        if fast.get("comment"):
            st.markdown(f"**종합**: {fast['comment']}")
        if fast.get("watch"):
            st.caption(f"👀 주목: {fast['watch']}")

        tech = (s.get("snap") or {}).get("tech") or {}
        meta = []
        if s.get("price") is not None:
            meta.append(f"현재가 {fmt(s['price'])} {s['currency']}")
        if s.get("pnl_pct") is not None:
            meta.append(f"손익 {s['pnl_pct']:+.1f}%")
        if tech.get("sma50"):
            meta.append(f"50일선 {tech['sma50']}")
        if tech.get("rsi14"):
            meta.append(f"RSI {tech['rsi14']}")
        if meta:
            st.caption(" · ".join(meta))

        # 심층 분석 버튼
        tkr = s["ticker"]
        dp = deep_path(tkr, result["trade_date"])
        cached_deep = deep_cache.get(tkr)
        if cached_deep is None and os.path.exists(dp):
            try:
                cached_deep = json.load(open(dp, encoding="utf-8"))
                deep_cache[tkr] = cached_deep
            except Exception:
                cached_deep = None

        if st.button(f"🔬 {tkr} 심층 분석 (TradingAgents)", key=f"deep_{tkr}"):
            with st.spinner(f"{tkr} 애널리스트 토론 진행 중... (1~2분, 무료 한도 주의)"):
                try:
                    deep = analyzer.deep_report(tkr, result["trade_date"])
                    deep_cache[tkr] = deep
                    json.dump(deep, open(dp, "w", encoding="utf-8"),
                              ensure_ascii=False, indent=2)
                    st.toast(f"{tkr} 심층 분석 완료")
                except Exception as e:  # noqa: BLE001
                    st.error(f"심층 분석 실패(무료 한도일 수 있어요): {e}")

        if deep_cache.get(tkr):
            d = deep_cache[tkr]
            st.markdown(f"**🔬 심층 결론: {d.get('rating','-')}**")
            st.markdown(d.get("reasoning") or d.get("decision") or "(내용 없음)")


# ── 4) 종목 간 시너지 ───────────────────────────────────────────────
st.markdown("---")
st.subheader("4️⃣ 종목 간 시너지 · 분산효과")

corr = result.get("correlation")
if corr and len(corr["tickers"]) >= 2:
    df = pd.DataFrame(corr["matrix"], index=corr["tickers"], columns=corr["tickers"])
    st.markdown("**① 일간 수익률 상관계수** (1에 가까울수록 같이 움직임, 낮/음수일수록 분산·헤지 효과)")
    st.dataframe(df.style.background_gradient(cmap="RdYlGn_r", vmin=-1, vmax=1)
                 .format("{:.2f}"), use_container_width=True)

# 다중공선성 · 분산 진단 (쌍별 상관을 넘어 '전체 구조' 점검)
diag = result.get("diagnostics")
if diag:
    st.markdown("**② 다중공선성 · 분산 진단** — 쌍별 상관은 낮아도 전체가 소수 요인에 얽혀 있는지 점검")
    d1, d2, d3, d4 = st.columns(4)
    n = diag["n"]
    eb = diag["effective_bets"]
    d1.metric("유효 베팅 수", f"{eb:.2f} / {n}",
              help="PCA 엔트로피 기반. 종목 수에 가까울수록 독립적 베팅이 많음(분산 양호).")
    d2.metric("최대 VIF", f"{diag['max_vif']:.2f}",
              help="분산팽창계수. 5 미만 양호, 5~10 주의, 10 이상 심각한 중복.")
    d3.metric("조건지수", f"{diag['condition_index']:.1f}",
              help="Belsley 조건지수. 30 이상이면 강한 공선성.")
    d4.metric("상관행렬 행렬식", f"{diag['determinant']:.3f}",
              help="1=서로 독립, 0에 가까울수록 전체가 얽힘(공선).")

    vif_df = pd.DataFrame({"종목": list(diag["vif"].keys()),
                           "VIF": list(diag["vif"].values())})
    cvv = st.columns([1, 1])
    with cvv[0]:
        st.caption("종목별 VIF (나머지 종목들로 설명되는 정도)")
        st.dataframe(vif_df, use_container_width=True, hide_index=True)
    with cvv[1]:
        st.caption("종합 판정")
        good = diag["flags"] == ["전반적으로 양호"]
        (st.success if good else st.warning)(" · ".join(diag["flags"]))
        st.caption(f"PC1이 전체 변동의 {diag['pc1_pct']}% 설명 · "
                   f"90% 설명에 {diag['n_for_90']}/{n}개 성분 필요 · 관측 {diag['n_obs']}일")

    with st.expander("📘 이 지표들 쉽게 이해하기"):
        st.markdown(
            "- **유효 베팅 수**: 종목이 4개라도 서로 비슷하게 움직이면 실제로는 2~3개에 "
            "베팅한 셈이에요. 종목 수에 가까울수록 진짜로 분산된 거예요.\n"
            "- **VIF**: 어떤 종목이 '나머지 종목들의 조합'으로 거의 설명되면 값이 커져요"
            "(중복 보유). 5를 넘으면 주의, 10을 넘으면 사실상 겹치는 베팅이에요.\n"
            "- **조건지수 / 행렬식**: 포트폴리오 '전체'가 하나의 큰 흐름(금리·달러 등)에 "
            "얽혀 있는 정도예요. 조건지수가 크거나(≥30) 행렬식이 0에 가까우면 겉보기보다 "
            "위험이 한곳에 쏠려 있다는 신호예요.\n"
            "- 쌍별 상관계수는 '둘씩'만 보지만, 이 지표들은 **여러 종목을 동시에** 봐서 "
            "숨은 공선성을 잡아내요.")

if result.get("synergy"):
    st.markdown(result["synergy"])
else:
    st.caption("종목이 2개 이상일 때 시너지 분석이 제공됩니다.")


# ── 5) 약점 보완 추천 (섹터/자산 편입 기대효과) ──────────────────────
st.markdown("---")
st.subheader("5️⃣ 약점 보완 추천 · 편입 기대효과")
st.caption("검증된 후보 자산(ETF)을 실제로 편입해 시뮬레이션한 뒤, 약점을 가장 잘 메우는 것을 추천해요.")

if st.button("🧭 약점 보완 후보 찾기 (시뮬레이션)"):
    import advisor
    with st.spinner("16개 후보 자산을 편입 시뮬레이션 중... (30초~1분)"):
        try:
            tks = [s["ticker"] for s in stocks if s.get("ticker")]
            rec = advisor.recommend(tks)
            desc = ", ".join(f"{s.get('name')}({s.get('ticker')})" for s in stocks)
            diag_text_ui = ""
            if result.get("diagnostics"):
                import risk as _risk
                diag_text_ui = _risk.to_text(result["diagnostics"])
            narr = advisor.explain(desc, diag_text_ui, rec) if rec else ""
            st.session_state.reco = {"rec": rec, "narr": narr}
        except Exception as e:  # noqa: BLE001
            st.error(f"추천 실패: {e}")

reco = st.session_state.get("reco")
if reco and reco.get("rec"):
    rec = reco["rec"]
    st.caption(f"현재 유효 베팅 {rec['eff_bets_before']} · 달성가능 최소변동성 {rec['minvar_vol_before']}%")
    cand_df = pd.DataFrame([{
        "후보": f"{c['name']} ({c['ticker']})",
        "성격": c["category"],
        "기존과 평균상관": c["avg_corr"],
        "유효베팅 변화": f"{c['eff_bets_before']}→{c['eff_bets_after']} (+{c['eff_bets_gain']})",
        "최소변동성 변화": f"{c['minvar_vol_before']}%→{c['minvar_vol_after']}% ({c['minvar_vol_delta']:+.1f}%p)",
    } for c in rec["candidates"]])
    st.dataframe(cand_df, use_container_width=True, hide_index=True)
    if reco.get("narr"):
        st.markdown(reco["narr"])
    st.caption("※ 상관이 낮고(또는 음수) 변동성을 크게 낮추는 후보일수록 분산에 유리해요.")
else:
    st.caption("버튼을 누르면 약점을 메울 후보와 그 기대효과를 계산해요.")


# ── 6) 이상적 재구성 시뮬레이션 ─────────────────────────────────────
st.markdown("---")
st.subheader("6️⃣ 이상적 재구성 시뮬레이션")
st.caption("기존 종목만으로 비중을 바꿨을 때의 과거 1년 성과 비교예요. (수익률은 과거 실적이며 미래를 보장하지 않아요.)")

rebal = result.get("rebalance")
if rebal:
    tbl = pd.DataFrame(rebal["table"])
    st.markdown("**비중안별 백테스트** (연율 기준, 관측 %d일)" % rebal["n_obs"])
    st.dataframe(
        tbl.style.format({"연율수익률": "{:.1f}%", "연율변동성": "{:.1f}%",
                          "샤프": "{:.2f}", "최대낙폭": "{:.1f}%", "분산비율": "{:.2f}"}),
        use_container_width=True, hide_index=True)

    st.markdown("**권장 비중(%)**")
    w = rebal["weights"]
    wdf = pd.DataFrame(w).T  # 행=구성안, 열=종목
    st.dataframe(wdf.style.format("{:.1f}"), use_container_width=True)
    st.caption("• **최소분산**: 변동성 최저(대신 소수 종목 집중) · **리스크패리티**: 각 종목이 "
               "위험에 고르게 기여(가장 균형적) · 수익률 예측이 필요 없어 견고한 방식이에요.")
else:
    st.caption("종목이 2개 이상이고 가격 이력이 있어야 시뮬레이션돼요.")


# ── 7) 적정가 모니터링 & 알림 ───────────────────────────────────────
st.markdown("---")
st.subheader("7️⃣ 적정가 모니터링 & 알림")
st.caption("추천이 나와도 지금 밸류에이션이 비싸면 불리해요. 종목별 '관심 매수가'를 정해두면, "
           "그 가격에 도달했을 때 매일 감시 스크립트가 알림을 줘요.")

import valuation as _val

# 발생한 알림 배너
_alerts_path = os.path.join(common.CACHE_DIR, "alerts.json")
if os.path.exists(_alerts_path):
    try:
        _alerts = json.load(open(_alerts_path, encoding="utf-8"))
        recent = [a for a in _alerts if a.get("date") == dt.date.today().isoformat()]
        if recent:
            st.success("🔔 오늘 관심가 도달: " +
                       " / ".join(f"{a['ticker']} {a['price']}(관심 {a['buy_price']})" for a in recent))
    except Exception:
        pass

val_rows = []
VERDICT_ICON = {"매수 매력 구간": "🟢", "관심가 이하 — 매수 검토": "🟢",
                "중립": "🟡", "밸류에이션 부담 — 대기": "🔴"}
for s in stocks:
    v = s.get("valuation")
    if not v:
        continue
    icon = VERDICT_ICON.get(v.get("verdict"), "⚪")
    val_rows.append({
        "종목": f"{s.get('name','?')} ({v['ticker']})",
        "현재가": f"{fmt(v.get('price'))} {v.get('currency','')}",
        "적정가": (f"{fmt(v.get('fair_value'))}" if v.get("fair_value") else "-"),
        "적정가 근거": v.get("fair_basis", "-"),
        "관심 매수가": (f"{fmt(v.get('watch_buy'))}" if v.get("watch_buy") else "-"),
        "상승여력": (f"{v['upside_pct']:+.1f}%" if v.get("upside_pct") is not None else "-"),
        "선행PER": (f"{v['forward_pe']:.1f}" if v.get("forward_pe") else "-"),
        "판정": f"{icon} {v.get('verdict','-')}",
    })
if val_rows:
    st.dataframe(pd.DataFrame(val_rows), use_container_width=True, hide_index=True)
    st.caption("🔴 대기 = 현재가가 적정가에 근접/초과(지금 매수 불리) · 🟢 = 관심가 이하로 매수 검토 구간. "
               "적정가는 애널리스트 목표주가·선행PER·200일선 기반 참고치예요.")

    # 관심 매수가 등록 (알림 대상)
    st.markdown("**관심 매수가 등록** — 알림 받고 싶은 종목의 가격을 정해 저장하세요.")
    watch = _val.load_watch()
    reg_rows = []
    for s in stocks:
        v = s.get("valuation")
        if not v or not v.get("ticker"):
            continue
        tkr = v["ticker"]
        default_price = watch.get(tkr, {}).get("buy_price") or v.get("watch_buy")
        reg_rows.append({"종목": s.get("name"), "티커": tkr,
                         "관심 매수가": default_price,
                         "현재가": v.get("price")})
    reg_df = st.data_editor(
        pd.DataFrame(reg_rows), use_container_width=True, hide_index=True,
        disabled=["종목", "티커", "현재가"], key="watch_editor",
        column_config={"관심 매수가": st.column_config.NumberColumn(
            "관심 매수가", help="현재가가 이 값 이하로 내려오면 알림")})
    if st.button("🔔 관심 매수가 저장 (매일 감시)"):
        targets = {}
        for r in reg_df.to_dict("records"):
            if r.get("티커") and r.get("관심 매수가"):
                targets[r["티커"]] = {"buy_price": float(r["관심 매수가"]),
                                    "note": r.get("종목", "")}
        _val.save_watch(targets)
        st.toast(f"{len(targets)}종목 감시 등록 완료. 매일 자동 확인해요.")
    st.caption("감시는 매일 자동 실행돼요(작업 스케줄러 'PortfolioPriceCheck'). "
               "도달 시 Windows 알림 + 이 화면 상단 배너로 알려드려요.")


# ── 8) 이메일 발송 ──────────────────────────────────────────────────
st.markdown("---")
st.subheader("8️⃣ 이메일로 리포트 보내기")
st.caption("리포트 초안을 자동으로 채워드려요. 직접 고쳐서 보낼 수 있어요.")

_ecfg = emailer.load_config()
with st.expander("✉️ 이메일 설정 (최초 1회) — Gmail 앱 비밀번호 필요", expanded=not _ecfg.get("sender")):
    st.markdown("Gmail은 일반 비밀번호가 아니라 **앱 비밀번호(16자리)**가 필요해요. "
                "[발급: Google 계정 → 보안 → 2단계 인증 → 앱 비밀번호]. "
                "설정은 이 PC에만 저장돼요(평문).")
    ec1, ec2 = st.columns(2)
    with ec1:
        _sender = st.text_input("보내는 Gmail", value=_ecfg.get("sender", ""))
        _recipient = st.text_input("받는 이메일", value=_ecfg.get("recipient", "") or _ecfg.get("sender", ""))
        _base_url = st.text_input("앱 공개 URL (구독/해지 링크용)",
                                  value=_ecfg.get("base_url", "http://localhost:8502"),
                                  help="배포 후 실제 주소로 바꾸세요. 예: https://...streamlit.app")
    with ec2:
        _pw = st.text_input("앱 비밀번호", value=_ecfg.get("app_password", ""), type="password")
        _owner_pw_set = st.text_input("소유자 비밀번호(공개 배포 시 대시보드 보호)",
                                      value=_ecfg.get("owner_password", ""), type="password",
                                      help="설정하면 방문자는 구독 기능만, 소유자만 로그인 후 전체 이용")
        _weekly = st.checkbox("📅 주간 리포트 자동 메일 받기 (매주 월 08:30)",
                              value=_ecfg.get("weekly_report_enabled", False))
        _alerts = st.checkbox("🔔 가격 알림도 이메일로 받기",
                              value=_ecfg.get("alerts_enabled", False))
    if st.button("💾 이메일 설정 저장"):
        _new = dict(_ecfg)
        _new.update({"smtp_host": "smtp.gmail.com", "smtp_port": 465,
                     "sender": _sender.strip(), "app_password": _pw.strip(),
                     "recipient": _recipient.strip(), "alerts_enabled": _alerts,
                     "weekly_report_enabled": _weekly, "base_url": _base_url.strip(),
                     "owner_password": _owner_pw_set.strip()})
        emailer.save_config(_new)
        st.toast("이메일 설정을 저장했어요.")
        _ecfg = emailer.load_config()

# 작성란
_subj = st.text_input("제목", value=emailer.default_subject(result), key="mail_subj")
if "mail_body" not in st.session_state:
    st.session_state.mail_body = emailer.default_body(result)
mc1, mc2 = st.columns([1, 4])
with mc1:
    if st.button("🔄 초안 다시 채우기"):
        st.session_state.mail_body = emailer.default_body(result)
_body = st.text_area("본문", key="mail_body", height=320)

if st.button("📧 이메일 보내기", type="primary"):
    ok, msg = emailer.send(_subj, _body)
    (st.success if ok else st.error)(msg)


# ── 9) 구독자 관리 & 뉴스레터 발송 (소유자용) ────────────────────────
st.markdown("---")
st.subheader("9️⃣ 구독자 관리 & 뉴스레터 발송")
_sc = subscribers.counts()
sm1, sm2, sm3 = st.columns(3)
sm1.metric("확인된 구독자", _sc["confirmed"])
sm2.metric("확인 대기", _sc["pending"])
sm3.metric("수신거부", _sc["unsubscribed"])
st.caption(f"구독/해지 링크 기준 URL: {_ecfg.get('base_url','(미설정)')} "
           "— 배포 후 실제 주소로 설정해야 링크가 작동해요.")

_nl_subj = st.text_input("뉴스레터 제목", value=emailer.default_subject(result), key="nl_subj")
if "nl_body" not in st.session_state:
    st.session_state.nl_body = emailer.default_body(result)
if st.button("🔄 뉴스레터 초안 채우기"):
    st.session_state.nl_body = emailer.default_body(result)
_nl_body = st.text_area("뉴스레터 본문 (각 메일에 수신거부 링크가 자동 첨부돼요)",
                        key="nl_body", height=240)
st.warning("⚠️ 개인 Gmail은 하루 발송 한도(~500)·스팸 차단 위험이 있어요. "
           "구독자가 많아지면 전용 이메일 서비스(SendGrid/Brevo 등)로 바꿔야 해요.")
if st.button(f"📤 확인된 구독자 {_sc['confirmed']}명에게 발송", type="primary"):
    if _sc["confirmed"] == 0:
        st.info("아직 확인된 구독자가 없어요.")
    else:
        with st.spinner("발송 중..."):
            res = subscribers.send_newsletter(
                _nl_subj, _nl_body, _ecfg.get("base_url", ""), _ecfg)
        st.success(f"발송 완료: 성공 {res['sent']} / 실패 {res['failed']} (총 {res['total']})")
        if res["errors"]:
            st.error("실패 목록:\n- " + "\n- ".join(res["errors"][:10]))


st.markdown("---")
st.caption("이 리포트는 AI가 공개 데이터로 생성한 참고자료입니다. 투자 결정과 그 결과의 책임은 전적으로 본인에게 있습니다.")
