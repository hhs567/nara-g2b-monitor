import os
import json
import time
import hashlib
import requests
from datetime import datetime, timedelta

API_URL = "https://www.lofin365.go.kr/lf/hub/QWGJK"

API_KEY = os.getenv("LOFIN_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SEEN_FILE = "seen_budget_ids.json"

if not API_KEY:
    raise ValueError("LOFIN_API_KEY가 설정되어 있지 않습니다.")

if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN이 설정되어 있지 않습니다.")

if not TELEGRAM_CHAT_ID:
    raise ValueError("TELEGRAM_CHAT_ID가 설정되어 있지 않습니다.")


# ============================================================
# 검색 키워드
# ============================================================

STRONG_KEYWORDS = [
    "도시기본계획",
    "도시관리계획",
    "도시계획",
    "지구단위계획",
    "도시개발",
    "도시재생",
    "정비계획",
    "개발계획",
    "성장관리계획",
    "공간계획",
    "생활권계획",
    "역세권",
    "산업단지",
    "공업지역",
    "택지개발",
    "공공주택",
    "마스터플랜",
]

SUPPORT_KEYWORDS = [
    "기본구상",
    "타당성",
    "활성화",
    "정비",
    "재생",
    "개발",
    "조성",
    "계획수립",
    "전략",
    "후보지",
    "입지",
    "사업화",
]

SERVICE_KEYWORDS = [
    "용역",
    "연구",
    "조사",
    "컨설팅",
    "기본계획",
    "기본구상",
    "타당성조사",
    "계획수립",
]


# ============================================================
# 날짜 설정
# ============================================================

KST = datetime.utcnow() + timedelta(hours=9)

YEAR = str(KST.year)

# 우선 안정적으로 30일 전 데이터 조회
TARGET_DATE = KST - timedelta(days=30)
EXEC_DATE = TARGET_DATE.strftime("%Y%m%d")

print("=" * 70)
print("지방재정365 도시계획 예산 모니터")
print("=" * 70)

print("회계연도:", YEAR)
print("조회일자:", EXEC_DATE)


# ============================================================
# 기존 확인 이력
# ============================================================

def load_seen_ids():
    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except FileNotFoundError:
        return set()
    except Exception:
        return set()


def save_seen_ids(seen_ids):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(
            sorted(list(seen_ids)),
            f,
            ensure_ascii=False,
            indent=2
        )


seen_ids = load_seen_ids()


# ============================================================
# 텔레그램 전송
# ============================================================

def send_telegram(message):
    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": True,
    }

    response = requests.post(
        url,
        data=payload,
        timeout=30
    )

    response.raise_for_status()


# ============================================================
# 숫자 표시
# ============================================================

def format_money(value):
    try:
        return f"{int(value):,}원"
    except Exception:
        return str(value or "-")


# ============================================================
# 도시계획 관련 여부 판단
# ============================================================

def detect_keywords(project_name):
    project_name = project_name or ""

    strong_hits = [
        keyword
        for keyword in STRONG_KEYWORDS
        if keyword in project_name
    ]

    support_hits = [
        keyword
        for keyword in SUPPORT_KEYWORDS
        if keyword in project_name
    ]

    service_hits = [
        keyword
        for keyword in SERVICE_KEYWORDS
        if keyword in project_name
    ]

    # 강한 키워드는 단독으로 통과
    if strong_hits:
        return True, strong_hits + service_hits

    # 일반 키워드는 용역성 표현과 같이 있을 때 통과
    if support_hits and service_hits:
        return True, support_hits + service_hits

    return False, []


# ============================================================
# 고유 ID 생성
# ============================================================

def make_project_id(row):
    raw = "|".join([
        str(row.get("fyr", "")),
        str(row.get("laf_cd", "")),
        str(row.get("dept_cd", "")),
        str(row.get("dbiz_cd", "")),
        str(row.get("dbiz_nm", "")),
    ])

    return hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()


# ============================================================
# API 호출
# ============================================================

def call_api(page_index=1, page_size=1000):

    params = {
        "Key": API_KEY,
        "Type": "json",
        "pIndex": page_index,
        "pSize": page_size,
        "fyr": YEAR,
        "exe_ymd": EXEC_DATE,
    }

    for attempt in range(1, 4):

        try:

            print(
                f"API 접속 시도 "
                f"{attempt}/3 "
                f"(페이지 {page_index})"
            )

            response = requests.get(
                API_URL,
                params=params,
                timeout=(60, 60)
            )

            response.raise_for_status()

            return response.json()

        except requests.exceptions.RequestException as e:

            print("API 오류:", e)

            if attempt == 3:
                raise

            time.sleep(10)

    return None


# ============================================================
# 응답 구조에서 row 추출
# ============================================================

def extract_rows(data):

    if not isinstance(data, dict):
        return [], 0

    root = data.get("QWGJK")

    if not root:
        return [], 0

    total_count = 0
    rows = []

    for item in root:

        if "head" in item:

            head = item.get("head", [])

            for h in head:

                if isinstance(h, dict):

                    if "list_total_count" in h:
                        total_count = int(
                            h.get(
                                "list_total_count",
                                0
                            )
                        )

        if "row" in item:
            rows = item.get("row", [])

    return rows, total_count


# ============================================================
# 전체 데이터 조회
# ============================================================

PAGE_SIZE = 1000

first_data = call_api(
    page_index=1,
    page_size=PAGE_SIZE
)

rows, total_count = extract_rows(first_data)

print("전체 데이터 건수:", total_count)

all_rows = list(rows)

if total_count > PAGE_SIZE:

    total_pages = (
        total_count + PAGE_SIZE - 1
    ) // PAGE_SIZE

    print("전체 페이지 수:", total_pages)

    for page in range(2, total_pages + 1):

        data = call_api(
            page_index=page,
            page_size=PAGE_SIZE
        )

        page_rows, _ = extract_rows(data)

        all_rows.extend(page_rows)


print("수집 데이터:", len(all_rows), "건")


# ============================================================
# 도시계획 사업 검색
# ============================================================

matched = []

for row in all_rows:

    project_name = str(
        row.get("dbiz_nm", "")
    ).strip()

    is_match, hit_keywords = detect_keywords(
        project_name
    )

    if not is_match:
        continue

    project_id = make_project_id(row)

    matched.append({
        "id": project_id,
        "row": row,
        "keywords": sorted(
            list(set(hit_keywords))
        ),
    })


print("도시계획 관련 후보:", len(matched), "건")


# ============================================================
# 신규 건 선별 및 텔레그램 전송
# ============================================================

new_count = 0

for item in matched:

    project_id = item["id"]
    row = item["row"]
    keywords = item["keywords"]

    if project_id in seen_ids:
        continue

    region = row.get(
        "wa_laf_hg_nm",
        row.get("wa_laf_ng_nm", "-")
    )

    local_name = row.get(
        "laf_hg_nm",
        "-"
    )

    project_name = row.get(
        "dbiz_nm",
        "-"
    )

    exec_date = row.get(
        "exe_ymd",
        "-"
    )

    budget_amount = row.get(
        "bdg_cash_amt",
        row.get("capep", 0)
    )

    execution_amount = row.get(
        "ep_amt",
        0
    )

    account_name = row.get(
        "acnt_dv_nm",
        "-"
    )

    message = (
        "🚨 [지방재정365 도시계획 관련 사업]\n\n"
        f"지역: {region}\n"
        f"지자체: {local_name}\n"
        f"사업명: {project_name}\n"
        f"회계구분: {account_name}\n"
        f"집행일자: {exec_date}\n"
        f"예산 관련 금액: "
        f"{format_money(budget_amount)}\n"
        f"집행액: "
        f"{format_money(execution_amount)}\n"
        f"탐지키워드: "
        f"{', '.join(keywords)}"
    )

    try:

        send_telegram(message)

        seen_ids.add(project_id)

        new_count += 1

        print(
            "텔레그램 전송:",
            project_name
        )

        # Telegram 과다 전송 방지
        time.sleep(1)

    except Exception as e:

        print(
            "텔레그램 전송 실패:",
            project_name,
            e
        )


save_seen_ids(seen_ids)

print("=" * 70)
print("신규 텔레그램 전송:", new_count, "건")
print("모니터링 종료")
print("=" * 70)
