"""공용 유틸: .env 로딩, Gemini 호출, 이름→티커 변환, 가격/환율/기술지표.

이 대시보드는 상위 폴더(C:\\claude code)의 TradingAgents/.env 를 그대로 재사용한다.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from functools import lru_cache

import pandas as pd

# ── 경로: 상위 폴더(자동매매 프로젝트)를 재사용 ──────────────────────
PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
os.makedirs(CACHE_DIR, exist_ok=True)


HERE = os.path.dirname(os.path.abspath(__file__))


def load_env() -> None:
    """환경변수(.env) 로딩. 로컬(stock-dashboard/.env)을 먼저, 없으면/보완으로
    상위 폴더 .env를 읽는다. load_dotenv는 이미 설정된 값을 덮어쓰지 않으므로
    로컬 .env가 우선한다. 배포 시엔 로컬 .env(또는 호스팅 시크릿)만 있으면 된다."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    local_env = os.path.join(HERE, ".env")
    if os.path.exists(local_env):
        load_dotenv(local_env)
    parent_env = os.path.join(PARENT_DIR, ".env")
    if os.path.exists(parent_env):
        load_dotenv(parent_env)  # 로컬에 없는 값만 보완


load_env()

QUICK_MODEL = os.environ.get("TRADINGAGENTS_QUICK_THINK_LLM", "gemini-3.1-flash-lite")
DEEP_MODEL = os.environ.get("TRADINGAGENTS_DEEP_THINK_LLM", "gemini-3.5-flash")

FX_TICKERS = {"USD": "USDKRW=X", "EUR": "EURKRW=X", "JPY": "JPYKRW=X",
              "GBP": "GBPKRW=X", "HKD": "HKDKRW=X", "CNY": "CNYKRW=X", "KRW": None}


# ── Gemini 호출 ─────────────────────────────────────────────────────
@lru_cache(maxsize=1)
def _genai_client():
    from google import genai
    key = os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("GOOGLE_API_KEY가 .env에 없습니다.")
    return genai.Client(api_key=key)


def _retry_delay(msg: str, default: float = 5.0) -> float:
    m = re.search(r"retryDelay['\"]?:\s*['\"]?(\d+(?:\.\d+)?)s", msg) \
        or re.search(r"retry in (\d+(?:\.\d+)?)s", msg)
    return float(m.group(1)) + 0.5 if m else default


def gemini(prompt: str, model: str | None = None, temperature: float = 0.2,
           fallback: bool = True, max_retries: int = 3) -> str:
    """Gemini 텍스트 생성.

    무료 한도(429)에 걸리면: 짧은 지연은 재시도, 심층 모델의 일일 한도가
    소진되면 빠른 모델(QUICK_MODEL)로 자동 폴백한다.
    """
    from google.genai import types
    client = _genai_client()
    model = model or QUICK_MODEL
    cfg = types.GenerateContentConfig(temperature=temperature)
    tried_fallback = False
    last_err: Exception | None = None

    for attempt in range(max_retries):
        try:
            resp = client.models.generate_content(model=model, contents=prompt, config=cfg)
            return (resp.text or "").strip()
        except Exception as e:  # noqa: BLE001
            last_err = e
            msg = str(e)
            if "429" not in msg and "RESOURCE_EXHAUSTED" not in msg:
                raise
            # 심층 모델 한도 소진 → 빠른 모델로 폴백 (1회)
            if fallback and not tried_fallback and model != QUICK_MODEL:
                model, tried_fallback = QUICK_MODEL, True
                continue
            delay = _retry_delay(msg)
            if attempt < max_retries - 1 and delay <= 30:
                time.sleep(delay)
                continue
            raise
    assert last_err is not None
    raise last_err


def gemini_json(prompt: str, model: str | None = None) -> dict:
    """JSON 응답을 기대하는 Gemini 호출. 코드펜스/잡텍스트를 걷어내고 파싱."""
    raw = gemini(prompt + "\n\n반드시 유효한 JSON 객체 하나만 출력하세요. 설명·코드펜스 금지.",
                 model=model, temperature=0.1)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.lstrip().startswith("json"):
            raw = raw.lstrip()[4:]
    # 첫 { ~ 마지막 } 사이만 취함
    s, e = raw.find("{"), raw.rfind("}")
    if s >= 0 and e > s:
        raw = raw[s:e + 1]
    return json.loads(raw)


# ── 이름 → 티커 변환 ────────────────────────────────────────────────
def resolve_ticker(query: str, max_results: int = 6) -> list[dict]:
    """종목명/티커 문자열로 후보 목록을 돌려준다.

    반환: [{symbol, name, exchange, type}] (관련도 순). 없으면 빈 리스트.
    """
    import yfinance as yf
    query = (query or "").strip()
    if not query:
        return []
    out: list[dict] = []
    try:
        quotes = yf.Search(query, max_results=max_results).quotes
        for q in quotes:
            sym = q.get("symbol")
            if not sym:
                continue
            out.append({
                "symbol": sym,
                "name": q.get("shortname") or q.get("longname") or sym,
                "exchange": q.get("exchDisp") or q.get("exchange") or "",
                "type": q.get("quoteType") or "",
            })
    except Exception:
        pass
    # 검색이 비었지만 입력이 유효 티커면 그대로 사용
    if not out:
        try:
            fi = yf.Ticker(query).fast_info
            if getattr(fi, "last_price", None):
                out.append({"symbol": query.upper(), "name": query.upper(),
                            "exchange": "", "type": "TICKER"})
        except Exception:
            pass
    return out


def best_ticker(query: str) -> str | None:
    """후보 중 최상단(주식/ETF 우선)을 자동 선택."""
    cands = resolve_ticker(query)
    if not cands:
        return None
    for c in cands:  # 주식/ETF를 지수·통화보다 우선
        if c["type"] in ("EQUITY", "ETF"):
            return c["symbol"]
    return cands[0]["symbol"]


# ── 가격 / 환율 / 기술지표 ──────────────────────────────────────────
@lru_cache(maxsize=64)
def fx_to_krw(currency: str) -> float | None:
    import yfinance as yf
    if currency == "KRW":
        return 1.0
    t = FX_TICKERS.get(currency)
    if not t:
        return None
    try:
        return float(yf.Ticker(t).fast_info.last_price)
    except Exception:
        return None


def snapshot(ticker: str) -> dict:
    """yfinance로 종목 스냅샷(가격·펀더멘털·기술지표·뉴스)을 모은다."""
    import yfinance as yf
    tk = yf.Ticker(ticker)
    fi = tk.fast_info
    price = float(getattr(fi, "last_price", None) or 0) or None
    currency = getattr(fi, "currency", None) or "USD"

    info = {}
    try:
        info = tk.get_info() or {}
    except Exception:
        info = {}

    # 기술지표
    tech = {}
    try:
        hist = tk.history(period="1y", auto_adjust=True)
        if not hist.empty:
            close = hist["Close"].dropna()
            tech["sma50"] = round(float(close.tail(50).mean()), 2)
            tech["sma200"] = round(float(close.tail(200).mean()), 2)
            tech["chg_1m"] = _pct(close, 21)
            tech["chg_3m"] = _pct(close, 63)
            tech["chg_1y"] = _pct(close, 252)
            tech["rsi14"] = _rsi(close, 14)
            tech["hi_52w"] = round(float(close.tail(252).max()), 2)
            tech["lo_52w"] = round(float(close.tail(252).min()), 2)
    except Exception:
        pass

    # 뉴스 헤드라인
    news = []
    try:
        for n in (tk.news or [])[:6]:
            c = n.get("content") or n
            title = c.get("title") if isinstance(c, dict) else None
            if title:
                news.append(title)
    except Exception:
        pass

    return {
        "ticker": ticker,
        "name": info.get("shortName") or info.get("longName") or ticker,
        "currency": currency,
        "price": price,
        "sector": info.get("sector") or "",
        "industry": info.get("industry") or "",
        "market_cap": info.get("marketCap"),
        "pe": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"),
        "dividend_yield": info.get("dividendYield"),
        "beta": info.get("beta"),
        "summary": (info.get("longBusinessSummary") or "")[:600],
        "tech": tech,
        "news": news,
    }


def _pct(close: pd.Series, n: int) -> float | None:
    if len(close) <= n:
        return None
    return round(float(close.iloc[-1] / close.iloc[-1 - n] - 1) * 100, 1)


def _rsi(close: pd.Series, period: int = 14) -> float | None:
    if len(close) < period + 1:
        return None
    delta = close.diff()
    up = delta.clip(lower=0).rolling(period).mean()
    down = (-delta.clip(upper=0)).rolling(period).mean()
    rs = up / down.replace(0, 1e-9)
    return round(float(100 - 100 / (1 + rs.iloc[-1])), 1)


def correlation_matrix(tickers: list[str], period: str = "6mo") -> pd.DataFrame | None:
    """일간 수익률 상관계수 행렬 (종목 간 시너지/분산효과 판단용)."""
    import yfinance as yf
    if len(tickers) < 2:
        return None
    try:
        data = yf.download(tickers, period=period, auto_adjust=True,
                           progress=False)["Close"]
        if isinstance(data, pd.Series):
            return None
        rets = data.pct_change().dropna(how="all")
        corr = rets.corr()
        return corr.round(2)
    except Exception:
        return None
