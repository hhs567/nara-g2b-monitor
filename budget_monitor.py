import os
import sys
import json
import time
import hashlib
import requests

from datetime import datetime, timedelta


# ============================================================
# 기본 설정
# ============================================================

API_URL = "https://www.lofin365.go.kr/lf/hub/QWGJK"

API_KEY = os.getenv("LOFIN_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SEEN_FILE = "seen_budget_ids.json"
SNAPSHOT_FILE = "budget_snapshot.json"
SOURCE_FILE = "budget_source_pages.json"


if not API_KEY:
    raise ValueError("LOFIN_API_KEY가 설정되어 있지 않습니다.")

if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN이 설정되어 있지 않습니다.")

if not TELEGRAM_CHAT_ID:
    raise ValueError("TELEGRAM_CHAT_ID가 설정되어 있지 않습니다.")


# ============================================================
# 대상 지역
# ============================================================

TARGET_REGIONS = {
    "4100000": "경기도",
    "5100000": "강원특별자치도",
    "4300000": "충청북도",
    "4400000": "충청남도",
}


# ============================================================
# 최신 데이터 탐색 설정
# ============================================================

# 오늘부터 며칠 전까지 데이터가 있는 날짜를 찾음
MAX_DATE_LOOKBACK = 35

# 실제 전체 지역 조회 실패 시 재시도 횟수
REGION_RETRY_COUNT = 2

# 연결 타임아웃
CONNECT_TIMEOUT = 15

# 응답 타임아웃
READ_TIMEOUT = 45

# API 재시도 간격
RETRY_SLEEP = 5


# ============================================================
# 도시계획 핵심 키워드
# ============================================================

STRONG_KEYWORDS = [
    "도시기본계획",
    "도시관리계획",
    "도시계획",
    "지구단위계획",
    "성장관리계획",
    "도시개발",
    "도시재생",
    "정비계획",
    "개발계획",
    "실시계획",
    "공간계획",
    "생활권계획",
    "역세권",
    "산업단지",
    "공업지역",
    "택지개발",
    "공공주택",
    "마스터플랜",
]


# ============================================================
# 보조 키워드
# ============================================================

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
    "설계",
    "기본계획",
]


# ============================================================
# 용역성 키워드
# ============================================================

SERVICE_KEYWORDS = [
    "용역",
    "연구용역",
    "조사용역",
    "설계용역",
    "계획수립",
    "수립용역",
    "기본계획",
    "기본구상",
    "타당성조사",
    "타당성 검토",
    "정비계획",
    "개발계획",
    "실시계획",
    "마스터플랜",
    "전략수립",
    "활성화계획",
    "기본설계",
]


# ============================================================
# 일반행정 / 비대상 제외 키워드
# ============================================================

EXCLUDE_KEYWORDS = [
    "운영비",
    "운영지원",
    "센터운영",
    "위원회",
    "회의수당",
    "수당",
    "여비",
    "출장",
    "교육",
    "연수",
    "워크숍",
    "행사",
    "축제",
    "홍보",
    "광고",
    "사무관리",
    "일반운영비",
    "업무추진비",
    "공공요금",
    "인건비",
    "기간제",
    "보조금",
    "민간보조",
    "민간이전",
    "민간경상",
    "출연금",
    "구입",
    "구매",
    "물품",
    "임차",
    "임대",
    "차량",
    "유류비",
    "유지관리",
    "시설관리",
    "시설물관리",

    "정비공사",
    "보수공사",
    "개선공사",
    "설치공사",
    "조성공사",
    "건축공사",
    "토목공사",
    "철거공사",
    "포장공사",
    "전기공사",
    "통신공사",
    "공사비",

    "재해예방",
    "재난",
    "소방",
    "상하수도",
    "보건",
    "복지",
    "농업",
    "축산",
    "산림",
]


# ============================================================
# 현재시간
# ============================================================

KST = datetime.utcnow() + timedelta(hours=9)
YEAR = str(KST.year)


print("=" * 78)
print("지방재정365 도시계획 예산 통합 모니터")
print("=" * 78)
print("회계연도:", YEAR)
print("대상지역:", ", ".join(TARGET_REGIONS.values()))
print("=" * 78)


# ============================================================
# 숫자 처리
# ============================================================

def safe_int(value):

    try:

        if value is None:
            return 0

        if isinstance(value, str):
            value = value.replace(",", "").strip()

        if value == "":
            return 0

        return int(float(value))

    except Exception:
        return 0


def format_money(value):

    return f"{safe_int(value):,}원"


# ============================================================
# JSON 읽기/저장
# ============================================================

def load_json_file(filename, default):

    try:

        with open(
            filename,
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)

    except FileNotFoundError:

        return default

    except Exception as e:

        print(
            f"{filename} 읽기 오류:",
            e
        )

        return default


def save_json_file(filename, data):

    with open(
        filename,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )


# ============================================================
# 기존 알림 이력
# ============================================================

seen_data = load_json_file(
    SEEN_FILE,
    []
)

if isinstance(seen_data, list):

    seen_ids = set(seen_data)

else:

    seen_ids = set()


# ============================================================
# 이전 스냅샷
# ============================================================

previous_snapshot = load_json_file(
    SNAPSHOT_FILE,
    {}
)

if not isinstance(
    previous_snapshot,
    dict
):

    previous_snapshot = {}


# ============================================================
# 예산 출처
# ============================================================

budget_sources = load_json_file(
    SOURCE_FILE,
    {}
)

if not isinstance(
    budget_sources,
    dict
):

    budget_sources = {}


# ============================================================
# Telegram
# ============================================================

def send_telegram(message):

    url = (
        "https://api.telegram.org/bot"
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
# 사업 ID
# ============================================================

def make_project_id(row):

    raw = "|".join([
        str(row.get("fyr", "")),
        str(row.get("wa_laf_cd", "")),
        str(row.get("laf_cd", "")),
        str(row.get("dept_cd", "")),
        str(row.get("dbiz_cd", "")),
        str(row.get("dbiz_nm", "")),
    ])

    return hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()


# ============================================================
# 지자체명 정리
# ============================================================

def normalize_local_name(local_name):

    local_name = str(
        local_name or ""
    ).strip()

    if local_name.endswith("본청"):

        local_name = local_name[:-2]

    return local_name


# ============================================================
# 예산 출처 조회
# ============================================================

def get_budget_source(local_name):

    local_name = normalize_local_name(
        local_name
    )

    source = budget_sources.get(
        local_name
    )

    if not source:

        return {
            "available": False,
            "source_name": "지방재정365 세부사업별 세출현황",
            "source_url": "",
            "latest_budget_title": "",
            "latest_budget_date": "",
            "status": "지방재정365 공식 데이터",
        }

    source_url = source.get(
        "source_url",
        ""
    )

    if source_url:

        status = "공식 예산서 게시판 확인 가능"

    else:

        status = "공식 예산서 URL 확인 중"

    return {
        "available": True,
        "source_name": source.get(
            "source_name",
            f"{local_name} 공식 예산정보"
        ),
        "source_url": source_url,
        "latest_budget_title": source.get(
            "latest_budget_title",
            ""
        ),
        "latest_budget_date": source.get(
            "latest_budget_date",
            ""
        ),
        "status": status,
    }


# ============================================================
# 일반행정 제외
# ============================================================

def is_excluded_project(project_name):

    return any(
        keyword in project_name
        for keyword in EXCLUDE_KEYWORDS
    )


# ============================================================
# 도시계획 관련성
# ============================================================

def detect_keywords(project_name):

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

    very_strong = [
        "도시기본계획",
        "도시관리계획",
        "지구단위계획",
        "성장관리계획",
    ]

    # 도시계획 자체인 사업
    if any(
        keyword in project_name
        for keyword in very_strong
    ):

        return (
            True,
            strong_hits,
            support_hits,
            service_hits
        )

    # 핵심 도시계획 분야 + 용역 성격
    if strong_hits and service_hits:

        return (
            True,
            strong_hits,
            support_hits,
            service_hits
        )

    return (
        False,
        strong_hits,
        support_hits,
        service_hits
    )


# ============================================================
# 발주가능성
# ============================================================

def calculate_rating(
    project_name,
    strong_hits,
    service_hits
):

    five_star = [
        "도시기본계획",
        "도시관리계획",
        "지구단위계획",
        "성장관리계획",
    ]

    if any(
        keyword in project_name
        for keyword in five_star
    ):

        return "★★★★★", "매우 높음"

    if strong_hits and "용역" in project_name:

        return "★★★★★", "매우 높음"

    four_star = [
        "기본구상",
        "타당성조사",
        "개발계획",
        "정비계획",
        "실시계획",
        "활성화계획",
        "마스터플랜",
        "기본설계",
    ]

    if any(
        keyword in project_name
        for keyword in four_star
    ):

        return "★★★★", "높음"

    if strong_hits and service_hits:

        return "★★★★", "높음"

    return "★★★", "검토 필요"


# ============================================================
# API 호출
# ============================================================

def call_api(
    region_code,
    exec_date,
    page_index=1,
    page_size=1000
):

    params = {
        "Key": API_KEY,
        "Type": "json",
        "pIndex": page_index,
        "pSize": page_size,
        "fyr": YEAR,
        "exe_ymd": exec_date,
        "wa_laf_cd": region_code,
    }

    region_name = TARGET_REGIONS[
        region_code
    ]

    for attempt in range(
        1,
        REGION_RETRY_COUNT + 1
    ):

        try:

            print(
                f"API {region_name} "
                f"{exec_date} "
                f"페이지 {page_index} "
                f"시도 {attempt}/"
                f"{REGION_RETRY_COUNT}"
            )

            response = requests.get(
                API_URL,
                params=params,
                timeout=(
                    CONNECT_TIMEOUT,
                    READ_TIMEOUT
                )
            )

            response.raise_for_status()

            data = response.json()

            print(
                f"✅ {region_name} "
                f"API 연결 성공"
            )

            return data

        except requests.exceptions.ConnectTimeout:

            print(
                f"⚠ {region_name} "
                "연결 시간 초과"
            )

        except requests.exceptions.ReadTimeout:

            print(
                f"⚠ {region_name} "
                "응답 시간 초과"
            )

        except requests.exceptions.RequestException as e:

            print(
                f"⚠ {region_name} "
                f"API 오류: {e}"
            )

        except ValueError as e:

            print(
                f"⚠ {region_name} "
                f"JSON 오류: {e}"
            )

        if attempt < REGION_RETRY_COUNT:

            time.sleep(RETRY_SLEEP)

    return None


# ============================================================
# API 응답 추출
# ============================================================

def extract_rows(data):

    if not isinstance(
        data,
        dict
    ):

        return [], 0

    root = data.get(
        "QWGJK"
    )

    if not root:

        return [], 0

    rows = []
    total_count = 0

    for item in root:

        if "head" in item:

            for head_item in item.get(
                "head",
                []
            ):

                if not isinstance(
                    head_item,
                    dict
                ):

                    continue

                if "list_total_count" in head_item:

                    total_count = safe_int(
                        head_item.get(
                            "list_total_count"
                        )
                    )

        if "row" in item:

            rows = item.get(
                "row",
                []
            )

    return (
        rows,
        total_count
    )


# ============================================================
# 최신 데이터 날짜 자동 탐색
# ============================================================

def find_latest_available_date():

    print()
    print("=" * 78)
    print("최신 지방재정365 데이터 날짜 자동 탐색")
    print("=" * 78)

    # 경기도를 대표지역으로 사용해 날짜 탐색
    probe_region = "4100000"

    for days_back in range(
        0,
        MAX_DATE_LOOKBACK + 1
    ):

        target_date = (
            KST
            - timedelta(days=days_back)
        )

        exec_date = target_date.strftime(
            "%Y%m%d"
        )

        print(
            "날짜 확인:",
            exec_date
        )

        data = call_api(
            probe_region,
            exec_date,
            1,
            1
        )

        if data is None:

            print(
                "→ 연결 실패"
            )

            continue

        rows, total_count = extract_rows(
            data
        )

        if total_count > 0 or rows:

            print()
            print(
                "✅ 최신 데이터 확인:",
                exec_date
            )

            return exec_date

        print(
            "→ 데이터 없음"
        )

        # 너무 빠르게 API를 치지 않도록
        time.sleep(1)

    return None


# ============================================================
# 최신 데이터 날짜 찾기
# ============================================================

EXEC_DATE = find_latest_available_date()


if not EXEC_DATE:

    message = (
        "⚠️ [예산 모니터 장애]\n\n"
        "최근 "
        f"{MAX_DATE_LOOKBACK}일 범위에서 "
        "지방재정365 데이터를 "
        "확인하지 못했습니다.\n\n"
        "기존 예산 이력과 스냅샷은 "
        "그대로 보존했습니다."
    )

    try:

        send_telegram(
            message
        )

    except Exception as e:

        print(
            "장애 알림 실패:",
            e
        )

    raise RuntimeError(
        "최신 지방재정365 데이터 날짜 탐색 실패"
    )


print()
print("=" * 78)
print("최종 조회 기준일:", EXEC_DATE)
print("=" * 78)


# ============================================================
# 4개 지역 전체 데이터 수집
# ============================================================

PAGE_SIZE = 1000

all_rows = []

successful_regions = []
failed_regions = []


for (
    region_code,
    region_name
) in TARGET_REGIONS.items():

    print()
    print("=" * 78)
    print("지역 조회:", region_name)
    print("=" * 78)

    first_data = call_api(
        region_code,
        EXEC_DATE,
        1,
        PAGE_SIZE
    )

    if first_data is None:

        failed_regions.append(
            region_name
        )

        print(
            f"❌ {region_name} "
            "조회 실패"
        )

        continue

    rows, total_count = extract_rows(
        first_data
    )

    successful_regions.append(
        region_name
    )

    print(
        region_name,
        "전체 데이터:",
        total_count,
        "건"
    )

    all_rows.extend(
        rows
    )

    if total_count <= PAGE_SIZE:

        continue

    total_pages = (
        total_count
        + PAGE_SIZE
        - 1
    ) // PAGE_SIZE

    print(
        region_name,
        "전체 페이지:",
        total_pages
    )

    for page in range(
        2,
        total_pages + 1
    ):

        page_data = call_api(
            region_code,
            EXEC_DATE,
            page,
            PAGE_SIZE
        )

        if page_data is None:

            print(
                f"⚠ {region_name} "
                f"{page}페이지 실패"
            )

            continue

        page_rows, _ = extract_rows(
            page_data
        )

        all_rows.extend(
            page_rows
        )


# ============================================================
# API 결과
# ============================================================

print()
print("=" * 78)

print(
    "API 성공 지역:",
    ", ".join(successful_regions)
    if successful_regions
    else "없음"
)

print(
    "API 실패 지역:",
    ", ".join(failed_regions)
    if failed_regions
    else "없음"
)

print("=" * 78)


# ============================================================
# 전체 실패
# ============================================================

if not successful_regions:

    error_message = (
        "⚠️ [예산 모니터 장애]\n\n"
        "지방재정365 API에 "
        "연결하지 못했습니다.\n\n"
        "📍 실패지역\n"
        + ", ".join(
            TARGET_REGIONS.values()
        )
        + "\n\n"
        "이번 실행에서는 신규 또는 "
        "증액 사업을 판단하지 않았습니다.\n"
        "기존 이력은 그대로 보존했습니다."
    )

    try:

        send_telegram(
            error_message
        )

    except Exception as e:

        print(
            "장애 Telegram 실패:",
            e
        )

    raise RuntimeError(
        "지방재정365 전체 지역 연결 실패"
    )


print()
print(
    "전체 수집:",
    len(all_rows),
    "건"
)


# ============================================================
# 도시계획 사업 필터
# ============================================================

matched = []

excluded_execution = 0
excluded_admin = 0
excluded_keyword = 0


for row in all_rows:

    project_name = str(
        row.get(
            "dbiz_nm",
            ""
        )
    ).strip()

    if not project_name:

        continue

    execution_amount = safe_int(
        row.get(
            "ep_amt",
            0
        )
    )

    # 집행 시작된 사업은 제외
    if execution_amount > 0:

        excluded_execution += 1

        continue

    if is_excluded_project(
        project_name
    ):

        excluded_admin += 1

        continue

    (
        is_match,
        strong_hits,
        support_hits,
        service_hits
    ) = detect_keywords(
        project_name
    )

    if not is_match:

        excluded_keyword += 1

        continue

    rating, rating_text = calculate_rating(
        project_name,
        strong_hits,
        service_hits
    )

    keywords = sorted(
        list(
            set(
                strong_hits
                + support_hits
                + service_hits
            )
        )
    )

    project_id = make_project_id(
        row
    )

    budget_amount = safe_int(
        row.get(
            "bdg_cash_amt",
            row.get(
                "capep",
                0
            )
        )
    )

    matched.append({
        "id": project_id,
        "row": row,
        "keywords": keywords,
        "rating": rating,
        "rating_text": rating_text,
        "budget_amount": budget_amount,
    })


print()
print("=" * 78)

print(
    "집행액 제외:",
    excluded_execution,
    "건"
)

print(
    "일반행정/비대상 제외:",
    excluded_admin,
    "건"
)

print(
    "도시계획 관련성 제외:",
    excluded_keyword,
    "건"
)

print(
    "최종 도시계획 용역 후보:",
    len(matched),
    "건"
)

print("=" * 78)


# ============================================================
# 현재 스냅샷 생성
# ============================================================

current_snapshot = {}


for item in matched:

    row = item[
        "row"
    ]

    project_id = item[
        "id"
    ]

    current_snapshot[
        project_id
    ] = {

        "project_name":
            row.get(
                "dbiz_nm",
                ""
            ),

        "region":
            TARGET_REGIONS.get(
                str(
                    row.get(
                        "wa_laf_cd",
                        ""
                    )
                ),
                row.get(
                    "wa_laf_ng_nm",
                    ""
                )
            ),

        "local_name":
            normalize_local_name(
                row.get(
                    "laf_hg_nm",
                    ""
                )
            ),

        "budget_amount":
            item[
                "budget_amount"
            ],

        "execution_amount":
            safe_int(
                row.get(
                    "ep_amt",
                    0
                )
            ),

        "exec_date":
            EXEC_DATE,
    }


# ============================================================
# 변화 유형 판별
# ============================================================

def detect_change(
    project_id,
    current_amount
):

    old = previous_snapshot.get(
        project_id
    )

    # 이전 스냅샷 자체가 없는 최초 실행
    if not previous_snapshot:

        return (
            "INITIAL",
            0
        )

    # 이전에 사업 자체가 없었음
    if old is None:

        return (
            "NEW",
            0
        )

    old_amount = safe_int(
        old.get(
            "budget_amount",
            0
        )
    )

    if current_amount > old_amount:

        return (
            "INCREASE",
            old_amount
        )

    if current_amount < old_amount:

        return (
            "DECREASE",
            old_amount
        )

    return (
        "SAME",
        old_amount
    )


# ============================================================
# Telegram 전송
# ============================================================

new_count = 0
increase_count = 0
normal_new_count = 0


for item in matched:

    project_id = item[
        "id"
    ]

    row = item[
        "row"
    ]

    project_name = row.get(
        "dbiz_nm",
        "-"
    )

    current_amount = item[
        "budget_amount"
    ]

    (
        change_type,
        old_amount
    ) = detect_change(
        project_id,
        current_amount
    )


    # --------------------------------------------------------
    # 기존 스냅샷과 동일하고 이미 알림한 사업은 제외
    # --------------------------------------------------------

    if (
        change_type == "SAME"
        and project_id in seen_ids
    ):

        continue


    # --------------------------------------------------------
    # 최초 스냅샷 구축 시 기존 사업 대량전송 방지
    # --------------------------------------------------------

    if change_type == "INITIAL":

        # 이미 알림한 사업이라면 그대로 건너뜀
        if project_id in seen_ids:

            continue

        # 과거 데이터 대량 발송 방지를 위해
        # 최초 스냅샷만 생성하고 신규 발송하지 않음
        continue


    # --------------------------------------------------------
    # 감소는 영업기회 알림에서는 제외
    # --------------------------------------------------------

    if change_type == "DECREASE":

        continue


    # --------------------------------------------------------
    # 동일하지만 seen에 없으면 신규 후보로 처리
    # --------------------------------------------------------

    if change_type == "SAME":

        if project_id in seen_ids:

            continue

        alert_type = "신규 확인"


    elif change_type == "NEW":

        alert_type = "신규 등장"


    elif change_type == "INCREASE":

        alert_type = "예산 증액"


    else:

        continue


    keywords = item[
        "keywords"
    ]

    rating = item[
        "rating"
    ]

    rating_text = item[
        "rating_text"
    ]


    region_code = str(
        row.get(
            "wa_laf_cd",
            ""
        )
    )

    region_name = TARGET_REGIONS.get(
        region_code,
        row.get(
            "wa_laf_ng_nm",
            "-"
        )
    )

    local_name = normalize_local_name(
        row.get(
            "laf_hg_nm",
            "-"
        )
    )

    department = (
        row.get("dept_nm")
        or row.get("dept_hg_nm")
        or "-"
    )

    account_name = row.get(
        "acnt_dv_nm",
        "-"
    )

    execution_amount = safe_int(
        row.get(
            "ep_amt",
            0
        )
    )

    source = get_budget_source(
        local_name
    )


    # ========================================================
    # 제목
    # ========================================================

    if alert_type == "신규 등장":

        header = (
            "🚨 [예산 신규사업 감지]"
        )

        normal_new_count += 1


    elif alert_type == "예산 증액":

        header = (
            "📈 [도시계획 예산 증액 감지]"
        )

        increase_count += 1


    else:

        header = (
            "🚨 [도시계획 신규 용역 후보]"
        )


    # ========================================================
    # Telegram 메시지
    # ========================================================

    message = (
        f"{header}\n\n"

        f"📌 변화유형 : "
        f"{alert_type}\n"

        f"🎯 발주가능성 : "
        f"{rating} ({rating_text})\n\n"

        f"📍 광역지역 : "
        f"{region_name}\n"

        f"🏢 지자체 : "
        f"{local_name}\n"

        f"🏛 담당부서 : "
        f"{department}\n\n"

        "📌 사업명\n"
        f"{project_name}\n\n"

        f"📂 회계구분 : "
        f"{account_name}\n"

        f"📅 지방재정365 기준일 : "
        f"{EXEC_DATE}\n\n"
    )


    # ========================================================
    # 예산 변동
    # ========================================================

    if alert_type == "예산 증액":

        increase_amount = (
            current_amount
            - old_amount
        )

        message += (
            "💰 예산 변동\n"
            f"기존 : "
            f"{format_money(old_amount)}\n"

            f"현재 : "
            f"{format_money(current_amount)}\n"

            f"증액 : "
            f"+{format_money(increase_amount)}\n\n"
        )

    else:

        message += (
            f"💰 예산관련금액 : "
            f"{format_money(current_amount)}\n\n"
        )


    message += (
        f"💳 집행액 : "
        f"{format_money(execution_amount)}\n"

        "✅ 집행액 0원\n\n"

        f"🔎 탐지키워드 : "
        f"{', '.join(keywords)}\n\n"

        "━━━━━━━━━━━━━━━━━━\n"

        "📑 예산 출처\n"

        f"{source['source_name']}\n"

        f"🔍 출처상태 : "
        f"{source['status']}\n"
    )


    # ========================================================
    # 공식 예산서 정보
    # ========================================================

    if source[
        "latest_budget_title"
    ]:

        message += (
            "\n📘 최근 확인 예산서\n"
            f"{source['latest_budget_title']}\n"
        )


    if source[
        "latest_budget_date"
    ]:

        message += (
            f"📅 게시일 : "
            f"{source['latest_budget_date']}\n"
        )


    if source[
        "source_url"
    ]:

        message += (
            "\n🔗 공식 예산서 확인\n"
            f"{source['source_url']}\n"
        )

    else:

        message += (
            "\n📌 기본 출처\n"
            "지방재정365 세부사업별 세출현황\n"
            "https://www.lofin365.go.kr/\n"
        )


    message += (
        "\n━━━━━━━━━━━━━━━━━━\n"

        "⚠ 신규 등장 또는 예산 증액은 "
        "지방재정365 데이터 변화 기준입니다.\n"

        "⚠ 본예산/제1회·제2회·제3회 추경 "
        "회차는 공식 예산서에서 "
        "최종 확인해야 합니다.\n"

        "⚠ 계약·발주 여부는 "
        "나라장터에서 별도 확인 필요"
    )


    # ========================================================
    # Telegram 전송
    # ========================================================

    try:

        send_telegram(
            message
        )

        seen_ids.add(
            project_id
        )

        new_count += 1

        print(
            "텔레그램 전송:",
            alert_type,
            region_name,
            local_name,
            project_name
        )

        time.sleep(1)

    except Exception as e:

        print(
            "텔레그램 전송 실패:",
            project_name,
            e
        )


# ============================================================
# 상태 저장
# ============================================================

save_json_file(
    SEEN_FILE,
    sorted(
        list(seen_ids)
    )
)

save_json_file(
    SNAPSHOT_FILE,
    current_snapshot
)


# ============================================================
# 최종 결과
# ============================================================

print()
print("=" * 78)

print(
    "최종 조회 기준일:",
    EXEC_DATE
)

print(
    "API 성공 지역:",
    ", ".join(
        successful_regions
    )
)

print(
    "API 실패 지역:",
    ", ".join(
        failed_regions
    )
    if failed_regions
    else "없음"
)

print(
    "도시계획 후보:",
    len(matched),
    "건"
)

print(
    "신규사업 감지:",
    normal_new_count,
    "건"
)

print(
    "예산 증액 감지:",
    increase_count,
    "건"
)

print(
    "신규 Telegram 전송:",
    new_count,
    "건"
)

print(
    "전체 알림 이력:",
    len(seen_ids),
    "건"
)

print(
    "스냅샷 사업:",
    len(current_snapshot),
    "건"
)

print(
    "모니터링 정상 종료"
)

print("=" * 78)
