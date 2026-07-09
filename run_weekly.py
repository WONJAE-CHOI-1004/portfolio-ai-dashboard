"""주간 스케줄용 헤드리스 실행: watchlist.json을 분석해 캐시에 저장.

Windows 작업 스케줄러가 run_weekly.cmd로 호출한다. 대시보드는 이 캐시를
읽어 최신 결과를 보여준다(브라우저를 안 켜도 매주 리포트가 갱신됨).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys

import common  # noqa: F401  (.env 로딩 + sys.path 설정)
import pipeline

HERE = os.path.dirname(os.path.abspath(__file__))
WATCHLIST_PATH = os.path.join(HERE, "watchlist.json")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    if not os.path.exists(WATCHLIST_PATH):
        print("watchlist.json이 없습니다. 대시보드에서 목록을 저장하세요.")
        return 1
    with open(WATCHLIST_PATH, encoding="utf-8") as f:
        holdings = json.load(f).get("holdings", [])
    if not holdings:
        print("분석할 종목이 없습니다.")
        return 1

    print(f"[{dt.datetime.now():%Y-%m-%d %H:%M}] 주간 분석 시작: {len(holdings)}종목")
    result = pipeline.run_portfolio(
        holdings, progress=lambda f, m: print(f"  {int(f*100):3d}% {m}"))
    pipeline.save_latest(result)

    # 이력 보관용 타임스탬프 파일도 저장
    ts_path = os.path.join(common.CACHE_DIR, f"report_{result['trade_date']}.json")
    with open(ts_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)

    totals = result.get("totals")
    if totals:
        print(f"완료. 총 손익(원화) {totals['pnl_krw']:+,.0f}원 "
              f"({totals['pnl_pct']:+.2f}%)")
    else:
        print("완료.")
    print(f"저장: {pipeline.LATEST_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
