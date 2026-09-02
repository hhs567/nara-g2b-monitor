# 나라장터 설계관련 용역 Telegram 모니터

무료로 운영할 수 있도록 **GitHub Actions + 공공데이터포털 API + Telegram Bot**으로 구성한 모니터입니다.

## 감시 대상

1. 나라장터 발주계획 - 용역
2. 나라장터 사전규격 - 용역
3. 나라장터 입찰공고 - 용역

검색어:

- 계획
- 설계
- 정비
- 구상
- 타당성
- 지정
- 재생
- 조성
- 시행
- 개발
- 검토
- 후보지
- 전략
- 조사
- 사업화

## 1. GitHub 저장소 만들기

GitHub에서 새 repository를 하나 만듭니다.

이 폴더의 파일을 repository 루트에 올립니다.

```text
nara_monitor.py
requirements.txt
.github/workflows/nara_monitor.yml
```

## 2. GitHub Secrets 설정

Repository → Settings → Secrets and variables → Actions → New repository secret

다음 5개를 만듭니다.

```text
G2B_ORDERPLAN_KEY
G2B_PRESPEC_KEY
G2B_BID_KEY
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
```

### G2B API 키

공공데이터포털에서 승인된 각 API의 **일반 인증키**를 넣습니다.

- G2B_ORDERPLAN_KEY = 발주계획현황서비스 키
- G2B_PRESPEC_KEY = 사전규격정보서비스 키
- G2B_BID_KEY = 입찰공고정보서비스 키

공공데이터포털에서 Encoding 키를 복사했더라도 프로그램에서 한 번 URL decode하므로 사용할 수 있습니다.

## 3. Telegram Bot 만들기

Telegram에서 `@BotFather`를 찾아 `/newbot`을 실행합니다.

Bot 이름과 username을 정하면 BotFather가 token을 줍니다.

예:

```text
123456789:AAxxxxxxxxxxxxxxxxxxxxxxxx
```

이 값을 `TELEGRAM_BOT_TOKEN` Secret에 넣습니다.

### Chat ID 확인

1. 만든 봇에게 먼저 `/start`를 보냅니다.
2. 브라우저에서 다음 주소를 엽니다.

```text
https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
```

3. JSON에서 다음 부분을 찾습니다.

```json
"chat": {
  "id": 123456789
}
```

그 숫자를 `TELEGRAM_CHAT_ID`에 넣습니다.

토큰은 절대 공개하지 마세요.

## 4. 실행

GitHub → Actions → `Nara G2B Monitor` → `Run workflow`

수동 실행을 한 번 해봅니다.

정상이라면 GitHub Actions 로그에:

```text
입찰공고 API 요청...
사전규격 API 요청...
발주계획 API 요청...
키워드 매칭: ...
Telegram 전송 완료...
```

가 표시됩니다.

이후 workflow가 10분마다 자동 실행됩니다.

## 5. 현재 버전의 중복 방지

이 버전은 한 번 실행하는 동안 같은 공고가 3개 API에서 중복으로 잡히는 것을 막습니다.

다만 GitHub Actions 실행 사이에 이미 알린 공고를 영구적으로 기억하는 저장소는 아직 넣지 않았습니다.

따라서 **완전한 중복 알림 방지**가 필요하면 다음 단계에서 GitHub artifact/cache 또는 별도 파일 저장 방식을 추가할 수 있습니다.

## 6. 조회 누락 방지

Workflow는 10분마다 실행하지만 `LOOKBACK_MINUTES=30`으로 최근 30분을 다시 조회합니다.

그래서 GitHub Actions가 몇 분 늦게 실행되거나 한 번 실행을 놓쳐도 다음 실행에서 다시 잡을 가능성을 높였습니다.

## 7. 주의

공공데이터포털 API의 일일 트래픽 제한이 있을 수 있습니다. `numOfRows=1000`을 사용하고 있으므로 실제 데이터량이 많은 경우 API 제한을 확인하면서 조정하세요.

또한 API 응답 필드명은 조달청 서비스 버전에 따라 일부 변경될 수 있습니다. 첫 수동 실행에서 API 응답 오류가 나오면 Actions 로그의 오류 메시지를 기준으로 수정하면 됩니다.
