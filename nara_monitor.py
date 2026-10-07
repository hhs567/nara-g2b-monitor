import os
import json
import time
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests


# ============================================================
# 기본 설정
# ============================================================

KST = ZoneInfo("Asia/Seoul")

SERVICE_KEY = os.environ.get("G2B_SERVICE_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

# GitHub Actions가 늦게 실행되어도 놓치지 않도록 3시간 조회
LOOKBACK_MINUTES = int(os.environ.get("LOOKBACK_MINUTES", "180"))

# API 조회
NUM_OF_ROWS = 100

# 상태 저장 파일
SEEN_FILE = "seen_ids.json"


# ============================================================
# 나라장터 API 주소
# ============================================================

API_ORDER_PLAN = (
    "https://apis.data.go.kr/1230000/ao/"
    "OrderPlanSttusService/getOrderPlanSttusListServc"
)

API_PRE_SPEC = (
    "https://apis.data.go.kr/1230000/ao/"
    "HrcspSsstndrdInfoService/getPublicPrcureThngInfoServc"
)

API_BID = (
    "https://apis.data.go.kr/1230000/ad/"
    "BidPublicInfoService/getBidPblancListInfoServc"
)


# ============================================================
# 1차 검색 키워드
# ============================================================

FIRST_KEYWORDS = [
    "계획",
    "설계",
    "정비",
    "구상",
    "타당성",
    "지정",
    "재생",
    "조성",
    "시행",
    "개발",
    "검토",
    "후보지",
    "전략",
    "조사",
    "사업화",
]


# ============================================================
# 2차 분야 필터
#
# 1차 키워드가 걸린 뒤 실제 도시계획 관련성 확인
# ============================================================

SECOND_CATEGORY_KEYWORDS = {

    "도시": [
        "도시",
        "도시계획",
        "도시개발",
        "도시관리",
        "도시기본계획",
        "도시관리계획",
        "도시재생",
        "도시정비",
        "도시공간",
        "생활권",
        "생활SOC",
        "지구단위계획",
        "개발계획",
        "개발사업",
        "정비계획",
        "정비사업",
        "재생사업",
        "기본계획",
        "관리계획",
        "공간계획",
        "공간구조",
        "토지이용",
        "토지이용계획",
        "광역도시",
        "도시권",
        "중심지",
        "역세권",
        "복합개발",
        "택지",
        "산업단지",
        "국가산업단지",
        "일반산업단지",
        "첨단산업단지",
        "산단",
        "도시첨단산업단지",
        "공업지역",
        "상업지역",
        "주거지역",
        "용도지역",
        "용도지구",
        "용도구역",
        "도시계획시설",
        "공원",
        "녹지",
        "광장",
        "도로",
        "교통",
        "광역교통",
        "주차장",
        "보행",
        "생활권계획",
        "스마트도시",
        "스마트시티",
        "콤팩트시티",
        "압축도시",
        "거점",
        "균형발전",
        "지역개발",
        "지역발전",
        "지역활성화",
        "지역재생",
        "원도심",
        "구도심",
        "신도시",
        "도시공간혁신",
        "도시혁신",
    ],

    "산업": [
        "산업단지",
        "산단",
        "산업혁신",
        "산업입지",
        "산업개발",
        "기업도시",
        "첨단산업",
        "미래산업",
        "신산업",
        "산업융합",
        "산업혁신구역",
        "복합산업",
    ],

    "교통": [
        "교통체계",
        "교통계획",
        "광역교통",
        "대중교통",
        "철도",
        "역세권",
        "도로",
        "도로망",
        "주차",
        "보행",
        "자전거",
        "환승센터",
        "환승",
        "BRT",
        "트램",
        "철도역",
    ],

    "주거": [
        "주택",
        "주거",
        "공공주택",
        "공공임대",
        "임대주택",
        "택지개발",
        "주거환경",
        "주거정비",
        "도시형생활주택",
        "공동주택",
        "정비구역",
        "재개발",
        "재건축",
    ],

    "지역개발": [
        "지역개발",
        "지역발전",
        "지역활성화",
        "지역재생",
        "균형발전",
        "생활권",
        "거점개발",
        "복합개발",
        "관광개발",
        "관광단지",
        "경제자유구역",
        "평화경제특구",
        "특화도시",
        "특화사업",
    ],
}


# ============================================================
# HTTP 설정
# ============================================================

REQUEST_TIMEOUT = 25

session = requests.Session()

session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/154.0 Safari/537.36"
    )
})


# ============================================================
# 공통 함수
# ============================================================

def clean_text(value):
    """HTML/XML/공백 등을 정리"""
    if value is None:
        return ""

    value = str(value)

    value = re.sub(r"<[^>]+>", " ", value)

    value = value.replace("&nbsp;", " ")
    value = value.replace("&amp;", "&")
    value = value.replace("&lt;", "<")
    value = value.replace("&gt;", ">")

    value = re.sub(r"\s+", " ", value)

    return value.strip()


def get_value(item, *keys):
    """
    여러 가능한 API 필드명 중 값이 있는 첫 번째 값을 반환
    """

    if not isinstance(item, dict):
        return ""

    # 직접 검색
    for key in keys:
        if key in item:
            value = clean_text(item.get(key))
            if value:
                return value

    # 대소문자 무시 검색
    lower_map = {
        str(k).lower(): v
        for k, v in item.items()
    }

    for key in keys:
        value = clean_text(lower_map.get(str(key).lower()))
        if value:
            return value

    return ""


def normalize_title(title):
    """
    제목 정리.
    이전에 'N'처럼 잘못된 값이 제목으로 잡히는 문제 방지.
    """

    title = clean_text(title)

    # 의미 없는 값
    if title.upper() in {
        "",
        "N",
        "NULL",
        "NONE",
        "N/A",
        "NA",
        "-"
    }:
        return ""

    return title


def now_kst():
    """현재 한국시간"""
    return datetime.now(KST)


def make_query_window():
    """
    ★ 핵심 수정사항

    과거 코드에서 UTC/KST가 섞이면서
    실제 현재시간보다 약 16시간 이전을 조회하는 문제가 발생할 수 있었음.

    현재는 무조건 Asia/Seoul 기준으로 계산.
    """

    end = now_kst() + timedelta(minutes=2)
    start = end - timedelta(minutes=LOOKBACK_MINUTES)

    return start, end


def format_api_datetime(dt):
    """
    나라장터 API용 YYYYMMDDHHMM
    """

    return dt.strftime("%Y%m%d%H%M")


def display_datetime(dt):
    return dt.strftime("%Y-%m-%d %H:%M")


# ============================================================
# 상태 파일
# ============================================================

def load_seen_ids():

    if not os.path.exists(SEEN_FILE):
        return set()

    try:
        with open(
            SEEN_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        if isinstance(data, list):
            return set(str(x) for x in data)

        return set()

    except Exception as e:

        print(f"[경고] seen_ids.json 읽기 실패: {e}")

        return set()


def save_seen_ids(seen_ids):

    # 너무 커지는 것을 방지
    recent_ids = list(seen_ids)[-10000:]

    with open(
        SEEN_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            recent_ids,
            f,
            ensure_ascii=False,
            indent=2
        )


# ============================================================
# API 호출
# ============================================================

def call_api(url, params, api_name):

    if not SERVICE_KEY:
        raise RuntimeError(
            "G2B_SERVICE_KEY 환경변수가 없습니다."
        )

    base_params = {
        "ServiceKey": SERVICE_KEY,
        "pageNo": 1,
        "numOfRows": NUM_OF_ROWS,
        "type": "JSON",
    }

    base_params.update(params)

    for attempt in range(1, 4):

        try:

            print(
                f"[API] {api_name} "
                f"시도 {attempt}/3"
            )

            response = session.get(
                url,
                params=base_params,
                timeout=REQUEST_TIMEOUT
            )

            print(
                f"[API] HTTP {response.status_code}"
            )

            response.raise_for_status()

            # JSON
            try:
                data = response.json()

            except Exception:

                # 혹시 JSON Content-Type 문제가 있는 경우
                text = response.text

                data = json.loads(text)

            return data

        except Exception as e:

            print(
                f"[API 오류] {api_name}: {e}"
            )

            if attempt < 3:
                time.sleep(3 * attempt)

    print(
        f"[API 실패] {api_name} "
        f"3회 모두 실패"
    )

    return {}


def extract_items(data):

    if not isinstance(data, dict):
        return []

    response = data.get("response", data)

    if not isinstance(response, dict):
        return []

    body = response.get("body", response)

    if not isinstance(body, dict):
        return []

    items = body.get("items", [])

    if isinstance(items, dict):
        item = items.get("item", [])

        if isinstance(item, list):
            return item

        if isinstance(item, dict):
            return [item]

    if isinstance(items, list):
        return items

    if isinstance(items, dict):
        return [items]

    return []


# ============================================================
# 제목 / 기관 / 금액 / 날짜 / ID 추출
# ============================================================

def get_title(item, api_type):

    if api_type == "pre_spec":

        title = get_value(
            item,
            "specNm",
            "prdctClsfcNoNm",
            "prdctClsfcNoNm",
            "bidNtceNm",
            "bidNtceDtlNm",
            "사업명",
            "품명",
            "사전규격명",
            "title",
            "ntceNm",
        )

    elif api_type == "order_plan":

        title = get_value(
            item,
            "bizNm",
            "orderPlanNm",
            "orderPlanDtlNm",
            "prdctClsfcNoNm",
            "bidNtceNm",
            "사업명",
            "용역명",
            "품명",
            "title",
        )

    else:

        title = get_value(
            item,
            "bidNtceNm",
            "bidNtceDtlNm",
            "bizNm",
            "prdctClsfcNoNm",
            "사업명",
            "용역명",
            "title",
            "ntceNm",
        )

    title = normalize_title(title)

    # 제목이 없으면 다른 문자열 필드에서 최대한 탐색
    if not title:

        candidates = []

        for key, value in item.items():

            value = normalize_title(value)

            if not value:
                continue

            # 너무 짧거나 숫자/코드인 값 제외
            if len(value) < 5:
                continue

            if re.fullmatch(r"[A-Za-z0-9_-]+", value):
                continue

            candidates.append(value)

        if candidates:
            # 가장 긴 자연어 문자열을 제목 후보로 사용
            title = max(
                candidates,
                key=len
            )

    return title or "제목 확인 필요"


def get_agency(item):

    return get_value(
        item,
        "dminsttNm",
        "dmndInsttNm",
        "orderInsttNm",
        "ntceInsttNm",
        "cntrctInsttNm",
        "institutionNm",
        "orgNm",
        "발주기관",
        "수요기관",
        "공고기관",
    ) or "기관 미상"


def get_amount(item):

    value = get_value(
        item,
        "asignBdgtAmt",
        "presmptPrce",
        "bdgtAmt",
        "orderPlanAmt",
        "budgetAmt",
        "totAmt",
        "배정예산액",
        "예산액",
        "추정가격",
    )

    if not value:
        return "미정"

    # 숫자만 있는 경우 천단위 표시
    numeric = re.sub(
        r"[^\d]",
        "",
        value
    )

    if numeric:

        try:
            return f"{int(numeric):,}원"
        except Exception:
            pass

    return value


def get_date(item, api_type):

    if api_type == "pre_spec":

        value = get_value(
            item,
            "rcptDt",
            "pubDt",
            "specRegDt",
            "regDt",
            "inqryBgnDt",
            "등록일시",
            "공개일시",
            "사전규격공개일시",
        )

    elif api_type == "order_plan":

        value = get_value(
            item,
            "orderPlanRegDt",
            "regDt",
            "orderPlanYm",
            "발주계획등록일시",
        )

    else:

        value = get_value(
            item,
            "bidNtceDt",
            "bidNtceDate",
            "regDt",
            "공고일시",
        )

    return value or "-"


def get_id(item, api_type):

    if api_type == "pre_spec":

        return get_value(
            item,
            "specRegNo",
            "specRegNo",
            "prdctClsfcNo",
            "bidNtceNo",
            "사전규격등록번호",
        )

    elif api_type == "order_plan":

        return get_value(
            item,
            "orderPlanNo",
            "orderPlanRegNo",
            "발주계획등록번호",
        )

    else:

        return get_value(
            item,
            "bidNtceNo",
            "bidNtceNo",
            "입찰공고번호",
        )


def get_link(item, api_type):

    link = get_value(
        item,
        "bidNtceDtlUrl",
        "bidNtceUrl",
        "ntceDtlUrl",
        "detailUrl",
        "url",
        "link",
    )

    if link:
        return link

    # URL이 없을 경우 나라장터 메인
    return "https://www.g2b.go.kr/"


# ============================================================
# 1차 키워드
# ============================================================

def find_first_keywords(text):

    text = clean_text(text)

    matched = []

    for keyword in FIRST_KEYWORDS:

        if keyword in text:
            matched.append(keyword)

    return matched


# ============================================================
# 2차 도시계획 분야
# ============================================================

def find_second_categories(text):

    text = clean_text(text)

    matched = []

    for category, keywords in SECOND_CATEGORY_KEYWORDS.items():

        for keyword in keywords:

            if keyword in text:

                matched.append(category)
                break

    return matched


# ============================================================
# 필터링
# ============================================================

def make_search_text(item, title):

    values = [
        title,
        get_agency(item),
    ]

    for key, value in item.items():

        if value is None:
            continue

        values.append(
            clean_text(value)
        )

    return " ".join(values)


def filter_item(item, api_type):

    title = get_title(
        item,
        api_type
    )

    search_text = make_search_text(
        item,
        title
    )

    first_matches = find_first_keywords(
        search_text
    )

    if not first_matches:
        return None

    second_matches = find_second_categories(
        search_text
    )

    if not second_matches:
        return None

    return {
        "title": title,
        "agency": get_agency(item),
        "amount": get_amount(item),
        "date": get_date(item, api_type),
        "id": get_id(item, api_type),
        "link": get_link(item, api_type),
        "first": first_matches,
        "second": second_matches,
        "api_type": api_type,
        "raw": item,
    }


# ============================================================
# Telegram
# ============================================================

def send_telegram(message):

    if not TELEGRAM_BOT_TOKEN:
        print("[Telegram] BOT TOKEN 없음")
        return False

    if not TELEGRAM_CHAT_ID:
        print("[Telegram] CHAT ID 없음")
        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": True,
    }

    for attempt in range(1, 4):

        try:

            response = session.post(
                url,
                data=payload,
                timeout=20
            )

            if response.status_code == 200:

                print("[Telegram] 전송 성공")
                return True

            print(
                f"[Telegram 오류] "
                f"{response.status_code} "
                f"{response.text[:300]}"
            )

        except Exception as e:

            print(
                f"[Telegram 오류] {e}"
            )

        time.sleep(2)

    return False


# ============================================================
# Telegram 메시지
# ============================================================

def make_message(result):

    api_type = result["api_type"]

    if api_type == "pre_spec":
        label = "🟡 B급/나라장터 사전규격"

    elif api_type == "order_plan":
        label = "🔵 A급/나라장터 발주계획"

    else:
        label = "🟢 C급/나라장터 입찰공고"

    first = ", ".join(
        result["first"]
    )

    second = ", ".join(
        result["second"]
    )

    message = (
        f"[{label}]\n"
        f"{result['title']}\n\n"
        f"발주기관: {result['agency']}\n"
        f"1차 검색어: {first}\n"
        f"2차 분야: {second}\n"
        f"금액: {result['amount']}\n"
        f"일시: {result['date']}\n"
        f"번호: {result['id']}\n"
        f"링크: {result['link']}"
    )

    return message


# ============================================================
# 사전규격 조회
# ============================================================

def fetch_pre_spec(start, end):

    params = {
        "inqryDiv": "1",
        "inqryBgnDt": format_api_datetime(start),
        "inqryEndDt": format_api_datetime(end),
    }

    print(
        "[사전규격 조회]"
        f" {format_api_datetime(start)}"
        f" ~ {format_api_datetime(end)}"
    )

    data = call_api(
        API_PRE_SPEC,
        params,
        "사전규격"
    )

    items = extract_items(data)

    print(
        f"[사전규격] {len(items)}건 조회"
    )

    return items


# ============================================================
# 발주계획 조회
# ============================================================

def fetch_order_plan(start, end):

    params = {
        "inqryDiv": "1",
        "inqryBgnDt": format_api_datetime(start),
        "inqryEndDt": format_api_datetime(end),
    }

    print(
        "[발주계획 조회]"
        f" {format_api_datetime(start)}"
        f" ~ {format_api_datetime(end)}"
    )

    data = call_api(
        API_ORDER_PLAN,
        params,
        "발주계획"
    )

    items = extract_items(data)

    print(
        f"[발주계획] {len(items)}건 조회"
    )

    return items


# ============================================================
# 입찰공고 조회
# ============================================================

def fetch_bid(start, end):

    params = {
        "inqryDiv": "1",
        "inqryBgnDt": format_api_datetime(start),
        "inqryEndDt": format_api_datetime(end),
    }

    print(
        "[입찰공고 조회]"
        f" {format_api_datetime(start)}"
        f" ~ {format_api_datetime(end)}"
    )

    data = call_api(
        API_BID,
        params,
        "입찰공고"
    )

    items = extract_items(data)

    print(
        f"[입찰공고] {len(items)}건 조회"
    )

    return items


# ============================================================
# 메인
# ============================================================

def main():

    print("=" * 70)
    print("나라장터 도시계획 수주기회 모니터링 시작")
    print("=" * 70)

    current = now_kst()

    print(
        f"[시작] "
        f"{current.isoformat()}"
    )

    start, end = make_query_window()

    print(
        f"[조회기간] "
        f"{display_datetime(start)}"
        f" ~ "
        f"{display_datetime(end)}"
    )

    print(
        f"[조회범위] 최근 "
        f"{LOOKBACK_MINUTES}분"
    )

    # --------------------------------------------------------
    # 상태
    # --------------------------------------------------------

    seen_ids = load_seen_ids()

    print(
        f"[기존 ID] "
        f"{len(seen_ids)}건"
    )

    all_results = []

    # --------------------------------------------------------
    # 1. 발주계획
    # --------------------------------------------------------

    try:

        items = fetch_order_plan(
            start,
            end
        )

        for item in items:

            result = filter_item(
                item,
                "order_plan"
            )

            if result:
                all_results.append(result)

    except Exception as e:

        print(
            f"[발주계획 오류] {e}"
        )

    # --------------------------------------------------------
    # 2. 사전규격
    # --------------------------------------------------------

    try:

        items = fetch_pre_spec(
            start,
            end
        )

        for item in items:

            result = filter_item(
                item,
                "pre_spec"
            )

            if result:
                all_results.append(result)

    except Exception as e:

        print(
            f"[사전규격 오류] {e}"
        )

    # --------------------------------------------------------
    # 3. 입찰공고
    # --------------------------------------------------------

    try:

        items = fetch_bid(
            start,
            end
        )

        for item in items:

            result = filter_item(
                item,
                "bid"
            )

            if result:
                all_results.append(result)

    except Exception as e:

        print(
            f"[입찰공고 오류] {e}"
        )

    print(
        f"[필터링 완료] "
        f"{len(all_results)}건"
    )

    # --------------------------------------------------------
    # 중복 제거
    # --------------------------------------------------------

    new_count = 0

    for result in all_results:

        item_id = result["id"]

        if not item_id:

            # ID가 없으면 제목+기관으로 임시 ID 생성
            item_id = (
                f"{result['api_type']}|"
                f"{result['title']}|"
                f"{result['agency']}"
            )

            result["id"] = item_id

        if item_id in seen_ids:

            print(
                f"[중복 제외] "
                f"{result['title']}"
            )

            continue

        # ----------------------------------------------------
        # Telegram
        # ----------------------------------------------------

        message = make_message(
            result
        )

        print(
            "\n"
            + "-" * 70
            + "\n"
            + message
            + "\n"
            + "-" * 70
        )

        success = send_telegram(
            message
        )

        if success:

            seen_ids.add(
                item_id
            )

            new_count += 1

            # 너무 빠른 연속 전송 방지
            time.sleep(1)

    # --------------------------------------------------------
    # 상태 저장
    # --------------------------------------------------------

    save_seen_ids(
        seen_ids
    )

    print("=" * 70)

    print(
        f"[완료] 신규 알림 "
        f"{new_count}건"
    )

    print(
        f"[최종 ID] "
        f"{len(seen_ids)}건"
    )

    print("=" * 70)


# ============================================================
# 실행
# ============================================================

if __name__ == "__main__":
    main()
