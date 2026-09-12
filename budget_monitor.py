import os
import json
import time
import requests
from datetime import datetime, timedelta

# ============================================================
# 지방재정365 세부사업별 세출현황 API 테스트
# - 오늘 기준 30일 전 데이터 조회
# ============================================================

API_URL = "https://www.lofin365.go.kr/lf/hub/QWGJK"
API_KEY = os.getenv("LOFIN_API_KEY")

if not API_KEY:
    raise ValueError("LOFIN_API_KEY가 설정되어 있지 않습니다.")

# ------------------------------------------------------------
# 한국시간 기준 날짜
# ------------------------------------------------------------

KST = datetime.utcnow() + timedelta(hours=9)

# 회계연도
YEAR = str(KST.year)

# 오늘 기준 30일 전
TARGET_DATE = KST - timedelta(days=30)

# 집행일자 형식: YYYYMMDD
EXEC_DATE = TARGET_DATE.strftime("%Y%m%d")

# ------------------------------------------------------------
# API 요청 파라미터
# ------------------------------------------------------------

params = {
    "Key": API_KEY,
    "Type": "json",
    "pIndex": 1,
    "pSize": 10,

    # 필수 검색인자
    "fyr": YEAR,
    "exe_ymd": EXEC_DATE,
}

print("=" * 60)
print("지방재정365 API 연결 테스트")
print("=" * 60)

print("회계연도:", YEAR)
print("조회 기준:", "오늘 기준 30일 전")
print("집행일자:", EXEC_DATE)

# ------------------------------------------------------------
# 인증키를 숨긴 요청 URL 확인
# ------------------------------------------------------------

prepared = requests.Request(
    "GET",
    API_URL,
    params=params
).prepare()

safe_url = prepared.url.replace(API_KEY, "*****")
print("요청 URL:", safe_url)

# ------------------------------------------------------------
# API 연결
# 최대 3회 재시도
# ------------------------------------------------------------

response = None

for attempt in range(1, 4):

    try:

        print()
        print(f"API 접속 시도 {attempt}/3")

        response = requests.get(
            API_URL,
            params=params,
            timeout=(60, 60)
        )

        print("API 서버 연결 성공")
        print("HTTP 상태코드:", response.status_code)

        break

    except requests.exceptions.ConnectTimeout:

        print(f"접속 시간 초과 - {attempt}/3")

        if attempt == 3:
            print("3회 모두 지방재정365 서버 접속에 실패했습니다.")
            raise

        print("10초 후 다시 시도합니다.")
        time.sleep(10)

    except requests.exceptions.ReadTimeout:

        print(f"응답 시간 초과 - {attempt}/3")

        if attempt == 3:
            print("3회 모두 응답 시간이 초과되었습니다.")
            raise

        print("10초 후 다시 시도합니다.")
        time.sleep(10)

    except requests.exceptions.RequestException as e:

        print("API 통신 오류:", e)
        raise

# ------------------------------------------------------------
# 응답 확인
# ------------------------------------------------------------

if response is None:
    raise RuntimeError("API 응답을 받지 못했습니다.")

response.raise_for_status()

print()
print("=" * 60)
print("[응답 내용]")
print("=" * 60)

try:

    data = response.json()

    print(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2
        )[:15000]
    )

except ValueError:

    print("JSON 형식이 아닙니다.")
    print()
    print(response.text[:10000])

print()
print("=" * 60)
print("지방재정365 API 테스트 종료")
print("=" * 60)
