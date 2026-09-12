import os
import requests
import json

# 지방재정365 OpenAPI
API_URL = "https://www.lofin365.go.kr/lf/hub/QWGJK"

# GitHub Secrets에서 인증키 가져오기
API_KEY = os.getenv("LOFIN_API_KEY")

if not API_KEY:
    raise ValueError("LOFIN_API_KEY가 설정되어 있지 않습니다.")

params = {
    "key": API_KEY,
    "type": "json",
    "pIndex": 1,
    "pSize": 10,
}

print("=" * 60)
print("지방재정365 API 연결 테스트")
print("=" * 60)

try:
    response = requests.get(
        API_URL,
        params=params,
        timeout=30
    )

    print("HTTP 상태코드:", response.status_code)
    print("요청 URL:", response.url.replace(API_KEY, "*****"))

    response.raise_for_status()

    print("\n[응답 내용]")
    
    try:
        data = response.json()
        print(json.dumps(
            data,
            ensure_ascii=False,
            indent=2
        )[:10000])

    except ValueError:
        print("JSON 형식이 아닙니다.")
        print(response.text[:5000])

except Exception as e:
    print("API 호출 오류:", e)
    raise
