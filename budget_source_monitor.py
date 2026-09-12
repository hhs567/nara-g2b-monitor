import os
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


if not API_KEY:
    raise ValueError(
        "LOFIN_API_KEY가 설정되어 있지 않습니다."
    )

if not TELEGRAM_BOT_TOKEN:
    raise ValueError(
        "TELEGRAM_BOT_TOKEN이 설정되어 있지 않습니다."
    )

if not TELEGRAM_CHAT_ID:
    raise ValueError(
        "TELEGRAM_CHAT_ID가 설정되어 있지 않습니다."
    )


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
# 공식 예산서 게시판
# 현재 확인된 지자체부터 등록
# 이후 계속 추가 가능
# ============================================================

BUDGET_SOURCE_PAGES = {

    "의정부시": (
        "https://www.ui4u.go.kr/portal/bbs/list.do"
        "?mId=0107010100&ptIdx=64"
    ),

}


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
# 일반 행정 / 비대상 사업 제외 키워드
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
]


# ============================================================
# 날짜 설정
#
# 현재까지 정상 확인된 방식인
# 30일 전 데이터를 조회
# ============================================================

KST = datetime.utcnow() + timedelta(hours=9)

YEAR = str(
    KST.year
)

TARGET_DATE = (
    KST
    - timedelta(days=30)
)

EXEC_DATE = TARGET_DATE.strftime(
    "%Y%m%d"
)


print("=" * 75)
print("지방재정365 도시계획 신규 용역 통합 모니터")
print("=" * 75)

print(
    "회계연도:",
    YEAR
)

print(
    "조회 기준일:",
    EXEC_DATE
)

print(
    "대상지역:",
    ", ".join(
        TARGET_REGIONS.values()
    )
)


# ============================================================
# 숫자 변환
# ============================================================

def safe_int(value):

    try:

        if value is None:
            return 0

        if isinstance(
            value,
            str
        ):

            value = (
                value
                .replace(",", "")
                .strip()
            )

        if value == "":
            return 0

        return int(
            float(value)
        )

    except Exception:

        return 0


def format_money(value):

    return (
        f"{safe_int(value):,}원"
    )


# ============================================================
# 기존 알림 이력
# ============================================================

def load_seen_ids():

    try:

        with open(
            SEEN_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

            if isinstance(
                data,
                list
            ):
                return set(
                    data
                )

            return set()

    except FileNotFoundError:

        return set()

    except Exception as e:

        print(
            "기존 이력 읽기 오류:",
            e
        )

        return set()


def save_seen_ids(seen_ids):

    with open(
        SEEN_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            sorted(
                list(seen_ids)
            ),
            f,
            ensure_ascii=False,
            indent=2
        )


seen_ids = load_seen_ids()


# ============================================================
# Telegram
# ============================================================

def send_telegram(message):

    url = (
        "https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}"
        "/sendMessage"
    )

    payload = {

        "chat_id":
            TELEGRAM_CHAT_ID,

        "text":
            message,

        "disable_web_page_preview":
            True,
    }

    response = requests.post(
        url,
        data=payload,
        timeout=30
    )

    response.raise_for_status()


# ============================================================
# 일반행정 제외
# ============================================================

def is_excluded_project(project_name):

    return any(
        keyword in project_name
        for keyword
        in EXCLUDE_KEYWORDS
    )


# ============================================================
# 도시계획 관련성 판별
# ============================================================

def detect_keywords(project_name):

    strong_hits = [

        keyword

        for keyword
        in STRONG_KEYWORDS

        if keyword
        in project_name
    ]


    support_hits = [

        keyword

        for keyword
        in SUPPORT_KEYWORDS

        if keyword
        in project_name
    ]


    service_hits = [

        keyword

        for keyword
        in SERVICE_KEYWORDS

        if keyword
        in project_name
    ]


    very_strong = [

        "도시기본계획",
        "도시관리계획",
        "지구단위계획",
        "성장관리계획",
    ]


    # --------------------------------------------------------
    # 매우 명확한 도시계획 사업
    # --------------------------------------------------------

    if any(
        keyword in project_name
        for keyword
        in very_strong
    ):

        return (
            True,
            strong_hits,
            support_hits,
            service_hits
        )


    # --------------------------------------------------------
    # 핵심 도시계획 + 용역성
    # --------------------------------------------------------

    if (
        strong_hits
        and service_hits
    ):

        return (
            True,
            strong_hits,
            support_hits,
            service_hits
        )


    # --------------------------------------------------------
    # 보조키워드 + 용역성
    # --------------------------------------------------------

    if (
        support_hits
        and service_hits
    ):

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
# 발주가능성 평가
# ============================================================

def calculate_rating(
    project_name,
    strong_hits,
    service_hits
):

    five_star_keywords = [

        "도시기본계획",
        "도시관리계획",

        "지구단위계획",
        "성장관리계획",
    ]


    if any(
        keyword in project_name
        for keyword
        in five_star_keywords
    ):

        return (
            "★★★★★",
            "매우 높음"
        )


    if (
        strong_hits
        and "용역"
        in project_name
    ):

        return (
            "★★★★★",
            "매우 높음"
        )


    four_star_keywords = [

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
        for keyword
        in four_star_keywords
    ):

        return (
            "★★★★",
            "높음"
        )


    if (
        strong_hits
        and service_hits
    ):

        return (
            "★★★★",
            "높음"
        )


    return (
        "★★★",
        "검토 필요"
    )


# ============================================================
# 사업 고유 ID
# ============================================================

def make_project_id(row):

    raw = "|".join([

        str(
            row.get(
                "fyr",
                ""
            )
        ),

        str(
            row.get(
                "wa_laf_cd",
                ""
            )
        ),

        str(
            row.get(
                "laf_cd",
                ""
            )
        ),

        str(
            row.get(
                "dept_cd",
                ""
            )
        ),

        str(
            row.get(
                "dbiz_cd",
                ""
            )
        ),

        str(
            row.get(
                "dbiz_nm",
                ""
            )
        ),
    ])


    return hashlib.sha256(
        raw.encode(
            "utf-8"
        )
    ).hexdigest()


# ============================================================
# API 호출
# ============================================================

def call_api(
    region_code,
    page_index=1,
    page_size=1000
):

    params = {

        "Key":
            API_KEY,

        "Type":
            "json",

        "pIndex":
            page_index,

        "pSize":
            page_size,

        "fyr":
            YEAR,

        "exe_ymd":
            EXEC_DATE,

        "wa_laf_cd":
            region_code,
    }


    for attempt in range(
        1,
        4
    ):

        try:

            print(
                f"API "
                f"{TARGET_REGIONS[region_code]} "
                f"페이지 {page_index} "
                f"시도 {attempt}/3"
            )


            response = requests.get(
                API_URL,
                params=params,
                timeout=(60, 90)
            )


            response.raise_for_status()


            return response.json()


        except requests.exceptions.RequestException as e:

            print(
                "API 오류:",
                e
            )


            if attempt == 3:

                print(
                    "해당 페이지 건너뜀"
                )

                return None


            time.sleep(
                attempt * 10
            )


    return None


# ============================================================
# API 응답 분석
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


                if (
                    "list_total_count"
                    in head_item
                ):

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
# 지자체명 정리
# ============================================================

def normalize_local_name(local_name):

    local_name = str(
        local_name or ""
    ).strip()


    # 예: 의정부시본청 → 의정부시
    if local_name.endswith(
        "본청"
    ):

        local_name = (
            local_name[:-2]
        )


    return local_name


# ============================================================
# 예산 출처
# ============================================================

def get_budget_source(local_name):

    local_name = normalize_local_name(
        local_name
    )


    source_url = (
        BUDGET_SOURCE_PAGES.get(
            local_name
        )
    )


    if source_url:

        return {

            "source_status":
                "공식 예산서 게시판 확인 가능",

            "budget_round":
                "추경 회차 자동확인 전",

            "source_name":
                f"{local_name} 공식 예산현황",

            "source_url":
                source_url,
        }


    return {

        "source_status":
            "지방재정365 사업정보 확인",

        "budget_round":
            "추경 회차 미확인",

        "source_name":
            "지방재정365 세부사업별 세출현황",

        "source_url":
            "",
    }


# ============================================================
# 지역별 데이터 수집
# ============================================================

PAGE_SIZE = 1000

all_rows = []


for (
    region_code,
    region_name
) in TARGET_REGIONS.items():


    print()
    print("=" * 75)

    print(
        "지역 조회:",
        region_name
    )

    print("=" * 75)


    first_data = call_api(
        region_code,
        1,
        PAGE_SIZE
    )


    rows, total_count = extract_rows(
        first_data
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
        "전체 페이지:",
        total_pages
    )


    for page in range(
        2,
        total_pages + 1
    ):


        page_data = call_api(
            region_code,
            page,
            PAGE_SIZE
        )


        if page_data is None:

            continue


        page_rows, _ = extract_rows(
            page_data
        )


        all_rows.extend(
            page_rows
        )


print()
print("=" * 75)

print(
    "4개 지역 전체 수집:",
    len(all_rows),
    "건"
)

print("=" * 75)


# ============================================================
# 필터
# ============================================================

matched = []

excluded_execution = 0

excluded_admin = 0

excluded_keyword = 0


for row in all_rows:


    # --------------------------------------------------------
    # 사업명
    # --------------------------------------------------------

    project_name = str(
        row.get(
            "dbiz_nm",
            ""
        )
    ).strip()


    if not project_name:

        continue


    # --------------------------------------------------------
    # 1. 집행액 있는 사업 제외
    # --------------------------------------------------------

    execution_amount = safe_int(
        row.get(
            "ep_amt",
            0
        )
    )


    if execution_amount > 0:

        excluded_execution += 1

        continue


    # --------------------------------------------------------
    # 2. 일반행정 제외
    # --------------------------------------------------------

    if is_excluded_project(
        project_name
    ):

        excluded_admin += 1

        continue


    # --------------------------------------------------------
    # 3. 도시계획 관련성
    # --------------------------------------------------------

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


    # --------------------------------------------------------
    # 4. 발주가능성
    # --------------------------------------------------------

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


    matched.append({

        "id":
            project_id,

        "row":
            row,

        "keywords":
            keywords,

        "rating":
            rating,

        "rating_text":
            rating_text,
    })


print()

print(
    "집행액 제외:",
    excluded_execution,
    "건"
)

print(
    "일반행정 제외:",
    excluded_admin,
    "건"
)

print(
    "관련성 제외:",
    excluded_keyword,
    "건"
)

print(
    "최종 도시계획 용역 후보:",
    len(matched),
    "건"
)


# ============================================================
# 신규 Telegram 알림
# ============================================================

new_count = 0


for item in matched:


    project_id = item[
        "id"
    ]


    if project_id in seen_ids:

        continue


    row = item[
        "row"
    ]


    keywords = item[
        "keywords"
    ]


    rating = item[
        "rating"
    ]


    rating_text = item[
        "rating_text"
    ]


    # --------------------------------------------------------
    # 지역
    # --------------------------------------------------------

    region_code = str(
        row.get(
            "wa_laf_cd",
            ""
        )
    )


    region_name = (
        TARGET_REGIONS.get(
            region_code,
            row.get(
                "wa_laf_ng_nm",
                "-"
            )
        )
    )


    # --------------------------------------------------------
    # 지자체
    # --------------------------------------------------------

    local_name_raw = row.get(
        "laf_hg_nm",
        "-"
    )


    local_name = normalize_local_name(
        local_name_raw
    )


    # --------------------------------------------------------
    # 사업명
    # --------------------------------------------------------

    project_name = row.get(
        "dbiz_nm",
        "-"
    )


    # --------------------------------------------------------
    # 담당부서
    # --------------------------------------------------------

    department = (

        row.get(
            "dept_nm"
        )

        or

        row.get(
            "dept_hg_nm"
        )

        or

        "-"
    )


    # --------------------------------------------------------
    # 회계
    # --------------------------------------------------------

    account_name = row.get(
        "acnt_dv_nm",
        "-"
    )


    # --------------------------------------------------------
    # 기준일
    # --------------------------------------------------------

    exec_date = row.get(
        "exe_ymd",
        "-"
    )


    # --------------------------------------------------------
    # 예산액
    # --------------------------------------------------------

    budget_amount = safe_int(

        row.get(

            "bdg_cash_amt",

            row.get(
                "capep",
                0
            )
        )
    )


    # --------------------------------------------------------
    # 집행액
    # --------------------------------------------------------

    execution_amount = safe_int(
        row.get(
            "ep_amt",
            0
        )
    )


    # --------------------------------------------------------
    # 예산 출처
    # --------------------------------------------------------

    source = get_budget_source(
        local_name
    )


    # --------------------------------------------------------
    # Telegram 메시지
    # --------------------------------------------------------

    message = (

        "🚨 [도시계획 신규 용역 후보]\n\n"

        f"🎯 발주가능성 : "
        f"{rating} "
        f"({rating_text})\n\n"

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
        f"{exec_date}\n\n"

        f"💰 예산관련금액 : "
        f"{format_money(budget_amount)}\n"

        f"💳 집행액 : "
        f"{format_money(execution_amount)}\n\n"

        f"🔎 탐지키워드 : "
        f"{', '.join(keywords)}\n\n"

        "━━━━━━━━━━━━━━━━━━\n"

        "📑 예산 출처\n"

        f"{source['source_name']}\n\n"

        f"📌 추경 회차 : "
        f"{source['budget_round']}\n"

        f"🔍 출처상태 : "
        f"{source['source_status']}\n"
    )


    # --------------------------------------------------------
    # 공식 예산서 링크
    # --------------------------------------------------------

    if source[
        "source_url"
    ]:

        message += (

            "\n🔗 공식 예산서 확인\n"

            f"{source['source_url']}\n"
        )


    message += (

        "\n━━━━━━━━━━━━━━━━━━\n"

        "✅ 집행액 0원\n"

        "→ 아직 예산 집행 전 사업\n"

        "⚠ 계약 또는 발주 여부는 "
        "나라장터에서 별도 확인 필요"
    )


    # --------------------------------------------------------
    # 전송
    # --------------------------------------------------------

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
            rating,
            region_name,
            local_name,
            project_name
        )


        time.sleep(
            1
        )


    except Exception as e:

        print(
            "텔레그램 전송 실패:",
            project_name,
            e
        )


# ============================================================
# 이력 저장
# ============================================================

save_seen_ids(
    seen_ids
)


# ============================================================
# 종료
# ============================================================

print()

print("=" * 75)

print(
    "신규 텔레그램 전송:",
    new_count,
    "건"
)

print(
    "전체 확인 이력:",
    len(seen_ids),
    "건"
)

print(
    "모니터링 정상 종료"
)

print("=" * 75)
