# 📈 포트폴리오 AI 리포트 대시보드

종목명을 입력하면 티커를 자동으로 찾아 **AI 리포트 · 손익 추이 · 다중공선성 진단 ·
종목 간 시너지 · 약점 보완 추천 · 재구성 시뮬레이션 · 적정가 모니터링 · 이메일 발송**을
한 화면에서 제공하는 개인용 Streamlit 대시보드입니다.

> ⚠️ 모든 내용은 공개 데이터로 생성한 **참고용 분석**이며, 투자 판단·책임은 본인에게 있습니다.

## 기능
1. 종목명 병렬 입력 → 자동 티커 변환(직접 입력도 가능)
2. 종목별 AI 요약(빠름) + 원하는 종목만 심층 분석(TradingAgents, 선택)
3. 손익 요약 + **손익 추이 그래프**(과거 시세·환율 복원)
4. 상관계수 + **다중공선성 진단**(VIF·조건지수·유효 베팅 수)
5. **약점 보완 추천** — 후보 자산을 실제 편입 시뮬레이션해 기대효과 계산
6. **이상적 재구성** — 최소분산·리스크패리티 비중 백테스트 비교
7. **적정가 모니터링** — 관심 매수가 도달 시 Windows/이메일 알림
8. **이메일 발송** — 리포트 초안을 작성해 전송

## 설치
```bash
pip install -r requirements.txt
cp .env.example .env      # 그리고 .env 에 본인 Gemini 키 입력
```
무료 Gemini 키: https://aistudio.google.com/apikey

## 실행
```bash
streamlit run dashboard.py --server.port 8502
```
Windows는 `실행하기.bat` 더블클릭.

## 자동화(선택, Windows 작업 스케줄러)
- `run_weekly.cmd` — 주간 전체 분석
- `run_price_check.cmd` — 매일 관심가 감시/알림

## 보안 주의
- `.env`, `email_config.json`(Gmail 앱 비밀번호), `watchlist.json`(개인 보유),
  `watch_targets.json`, `cache/`, `logs/` 는 **`.gitignore`로 커밋 제외**됩니다.
- 공개 배포 시 키는 저장소에 넣지 말고 호스팅 시크릿(예: Streamlit Cloud Secrets)에 넣으세요.
- 이메일은 개인 Gmail 기준입니다. 다수의 외부 수신자에게 대량 발송하려면 개인 Gmail이
  아니라 전용 이메일 서비스(SendGrid 등)와 수신 동의(opt-in)를 사용하세요.

## 심층 분석(선택)
'심층 분석' 버튼은 별도의 [TradingAgents](https://github.com/TauricResearch/TradingAgents)
설치가 필요합니다. 없으면 나머지 기능은 정상 동작하고 해당 버튼만 안내 메시지를 표시합니다.
