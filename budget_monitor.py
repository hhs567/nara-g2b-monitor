import os
import requests
import json
from datetime import datetime, timedelta

# ============================================================
# 지방재정365 세부사업별 세출현황 API 테스트
# ============================================================

API_URL = "https://www.lofin365.go.kr/lf/hub/QWGJK"
API_KEY = os.getenv("LOFIN_API_KEY")

if not API_KEY:
    raise ValueError("LOFIN_API_KEY가 설정되어 있지 않습니다.")

# 한국시간 기준 날짜
KST = datetime.utcnow() + timedelta(hours=9)

# 회계연도
YEAR = str(KST.year)

# 집행일자
# API 형식: YYYYMMDD
EXEC_DATE = KST.strftime("%Y%m%d")

params = {
    "Key": API_KEY,
    "Type": "json",
    "pIndex": 1,
    "pSize": 10,

    # 검색 필수값
    "fyr": YEAR,
    "exe_ymd": EXEC_DATE,
}

print("=" * 60)
print("지방재정365 API 연결 테스트")
print("=" * 60)

print("회계연도:", YEAR)
print("집행일자:", EXEC_DATE)

try:
    response = requests.get(
        API_URL,
        params=params,
        timeout=30
    )

    print("HTTP 상태코드:", response.status_code)

    # 인증키 노출 방지
    safe_url = response.url.replace(API_KEY, "*****")
    print("요청 URL:", safe_url)

    response.raise_for_status()

    print("\n[응답 내용]")

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
        print(response.text[:10000])

except Exception as e:

    print("API 호출 오류:", e)
    raise
