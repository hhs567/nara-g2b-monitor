
import os
import re
import json
import time
import sys
import requests
import xml.etree.ElementTree as ET

from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import unquote

# ==========================================
# 1. 기본 설정
# ==========================================

KST = ZoneInfo("Asia/Seoul")

SERVICE_KEY = os.getenv("G2B_SERVICE_KEY", "").strip()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

LOOKBACK_MINUTES = int(os.getenv("LOOKBACK_MINUTES", "180"))
SEEN_FILE = Path("seen_ids.json")

TIMEOUT = 35
RETRIES = 3
PAGE_SIZE = 100
MAX_PAGES = 10
MAX_SEEN = 20000

# ==========================================
# 2. 검색 키워드
# ==========================================

KEYWORDS = [
    "계획", "설계", "정비", "구상",
    "타당성", "지정", "재생", "조성",
    "시행", "개발", "검토", "후보지",
    "전략", "조사", "사업화"
]

# 도시계획 관련 2차 필터
FIELD_KEYWORDS = [
    "도시", "도시계획", "도시개발",
    "도시기본", "도시관리", "도시재생",
    "산업", "산업단지", "국가산단",
    "국가산업단지", "산단",
    "교통", "도로", "철도", "역세권",
    "주거", "주택", "공공주택",
    "택지", "지역개발", "균형발전",
    "공간", "공간계획", "국토",
    "토지", "입지", "지구단위",
    "생활권", "신도시", "정비사업",
    "재개발", "재건축", "공원",
    "녹지", "경관", "관광",
    "지역활성화", "농촌공간",
    "기본계획", "관리계획"
]

# 명백히 관련성이 낮은 공고를 제외
EXCLUDE_KEYWORDS = [
    "전산장비 유지보수",
    "정보시스템 유지보수",
    "홈페이지 유지보수",
    "소방시설 점검",
    "승강기 유지보수",
    "복사기 임차",
    "프린터 임차"
]

# ==========================================
# 3. 나라장터 API
# ==========================================

API_CONFIG = {
    "발주계획": {
        "url": (
            "https://apis.data.go.kr/1230000/ao/"
            "OrderPlanSttusService/"
            "getOrderPlanSttusListServc"
        ),
        "date_start": "inqryBgnDt",
        "date_end": "inqryEndDt"
    },
    "사전규격": {
        "url": (
            "https://apis.data.go.kr/1230000/ao/"
            "HrcspSsstndrdInfoService/"
            "getPublicPrcureThngInfoServc"
        ),
        "date_start": "inqryBgnDt",
        "date_end": "inqryEndDt"
    },
    "입찰공고": {
        "url": (
            "https://apis.data.go.kr/1230000/ad/"
            "BidPublicInfoService/"
            "getBidPblancListInfoServc"
        ),
        "date_start": "inqryBgnDt",
        "date_end": "inqryEndDt"
    }
}

# ==========================================
# 4. 공통 함수
# ==========================================

def log(message):
    print(message, flush=True)


def now_kst():
    return datetime.now(KST)


def clean_text(value):
    if value is None:
        return ""
    return str(value).strip()


def first_value(item, fields):
    for field in fields:
        value = clean_text(item.get(field))
        if value:
            return value
    return ""


def normalize_key(value):
    return re.sub(r"\s+", "", clean_text(value)).lower()


def is_relevant(title):
    normalized = normalize_key(title)

    if not normalized:
        return False

    first_pass = any(
        normalize_key(k) in normalized
        for k in KEYWORDS
    )

    second_pass = any(
        normalize_key(k) in normalized
        for k in FIELD_KEYWORDS
    )

    excluded = any(
        normalize_key(k) in normalized
        for k in EXCLUDE_KEYWORDS
    )

    return first_pass and second_pass and not excluded


def load_seen():
    if not SEEN_FILE.exists():
        return set()

    try:
        data = json.loads(
            SEEN_FILE.read_text(encoding="utf-8")
        )

        if isinstance(data, list):
            return set(str(x) for x in data)

        if isinstance(data, dict):
            return set(str(x) for x in data.keys())

    except Exception as e:
        log(f"[기존 ID 읽기 오류] {e}")

    return set()


def save_seen(seen):
    values = sorted(seen)

    if len(values) > MAX_SEEN:
        values = values[-MAX_SEEN:]

    temp_file = SEEN_FILE.with_suffix(".tmp")

    temp_file.write_text(
        json.dumps(values, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    temp_file.replace(SEEN_FILE)


# ==========================================
# 5. API 응답 해석
# ==========================================

def xml_to_dict(element):
    children = list(element)

    if not children:
        return clean_text(element.text)

    result = {}

    for child in children:
        tag = child.tag.split("}")[-1]
        value = xml_to_dict(child)

        if tag in result:
            if not isinstance(result[tag], list):
                result[tag] = [result[tag]]
            result[tag].append(value)
        else:
            result[tag] = value

    return result


def parse_response(response, category):
    body = response.content

    if not body or not body.strip():
        raise ValueError("API 응답 본문이 비어 있습니다.")

    content_type = response.headers.get(
        "Content-Type", ""
    ).lower()

    preview = response.text[:350].replace("\n", " ")

    log(f"[API] {category} Content-Type: {content_type}")

    stripped = body.lstrip()

    try:
        if stripped.startswith(b"{") or stripped.startswith(b"["):
            return response.json()

        if stripped.startswith(b"<"):
            root = ET.fromstring(body)
            return {root.tag.split("}")[-1]: xml_to_dict(root)}

        # 응답 첫 글자만으로 구분되지 않을 때
        try:
            return response.json()
        except ValueError:
            root = ET.fromstring(body)
            return {root.tag.split("}")[-1]: xml_to_dict(root)}

    except Exception as e:
        raise ValueError(
            f"응답 해석 실패: {e}; "
            f"본문 앞부분: {preview}"
        )


def find_api_error(data):
    if not isinstance(data, dict):
        return ""

    # 공공데이터포털 공통 오류
    for key in ("OpenAPI_ServiceResponse", "errorResponse"):
        if key in data:
            return f"{key}: {str(data[key])[:500]}"

    response = data.get("response", data)

    if not isinstance(response, dict):
        return ""

    header = response.get("header", {})

    if not isinstance(header, dict):
        return ""

    code = clean_text(header.get("resultCode"))
    message = clean_text(header.get("resultMsg"))

    if code and code not in ("00", "0", "000"):
        return f"API 오류 코드 {code}: {message}"

    return ""


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
        items = items.get("item", [])

    if isinstance(items, dict):
        return [items]

    if isinstance(items, list):
        return [x for x in items if isinstance(x, dict)]

    return []


def extract_total(data):
    response = data.get("response", data)

    if not isinstance(response, dict):
        return 0

    body = response.get("body", response)

    if not isinstance(body, dict):
        return 0

    try:
        return int(body.get("totalCount", 0))
    except (TypeError, ValueError):
        return 0


# ==========================================
# 6. API 호출
# ==========================================

def request_api(category, config, start, end, page):
    # Decoding 인증키를 기본으로 사용
    # 환경변수에 인코딩된 키가 있으면 한 번 디코딩
    key = unquote(SERVICE_KEY)

    params = {
        "serviceKey": key,
        "numOfRows": PAGE_SIZE,
        "pageNo": page,
        "type": "json",
        config["date_start"]: start,
        config["date_end"]: end
    }

    last_error = None

    for attempt in range(1, RETRIES + 1):
        try:
            log(
                f"[API] {category} "
                f"페이지 {page}, 시도 {attempt}/{RETRIES}"
            )

            response = requests.get(
                config["url"],
                params=params,
                timeout=TIMEOUT
            )

            log(f"[API] HTTP {response.status_code}")

            response.raise_for_status()

            data = parse_response(response, category)

            error = find_api_error(data)

            if error:
                raise ValueError(error)

            if not isinstance(data, dict):
                raise ValueError(
                    "API 응답의 최상위 구조가 올바르지 않습니다."
                )

            return data

        except (
            requests.RequestException,
            ValueError,
            ET.ParseError
        ) as e:
            last_error = e
            log(f"[API 오류] {category}: {e}")

            if attempt < RETRIES:
                time.sleep(attempt * 2)

    raise RuntimeError(
        f"{category} API {RETRIES}회 실패: {last_error}"
    )


def fetch_category(category, config, start, end):
    all_items = []

    for page in range(1, MAX_PAGES + 1):
        data = request_api(
            category, config, start, end, page
        )

        items = extract_items(data)
        total = extract_total(data)

        log(
            f"[{category}] 페이지 {page}: "
            f"{len(items)}건, 전체 {total}건"
        )

        all_items.extend(items)

        if not items:
            break

        if len(items) < PAGE_SIZE:
            break

        if total > 0 and page * PAGE_SIZE >= total:
            break

    return all_items


# ==========================================
# 7. 공고 정보 정리
# ==========================================

TITLE_FIELDS = [
    "orderPlanNm",
    "orderPlanName",
    "bsnsNm",
    "prdctClsfcNoNm",
    "prdctNm",
    "bfSpecNm",
    "preSpecNm",
    "bidNtceNm",
    "bidPblancNm",
    "ntceNm",
    "servcNm",
    "cntrctNm",
    "prcrmntNm",
    "pblancNm"
]

ID_FIELDS = [
    "orderPlanNo",
    "orderPlanRegNo",
    "bfSpecRgstNo",
    "preSpecRgstNo",
    "bidNtceNo",
    "bidPblancNo",
    "ntceNo",
    "rgstNo"
]

ORG_FIELDS = [
    "ntceInsttNm",
    "dminsttNm",
    "orderInsttNm",
    "insttNm",
    "dmandInsttNm",
    "prcrmntInsttNm"
]

DATE_FIELDS = [
    "rgstDt",
    "opengDt",
    "bidNtceDt",
    "ntceDt",
    "orderPlanDt",
    "bfSpecRgstDt"
]

AMOUNT_FIELDS = [
    "asignBdgtAmt",
    "asignBdgt",
    "bdgtAmt",
    "presmptPrce",
    "presmptPrceAmt",
    "orderPlanAmt"
]

URL_FIELDS = [
    "bidNtceDtlUrl",
    "bidNtceUrl",
    "detailUrl",
    "ntceUrl",
    "url"
]


def format_amount(value):
    value = clean_text(value)

    if not value:
        return "미표시"

    try:
        number = int(float(value.replace(",", "")))
        return f"{number:,}원"
    except ValueError:
        return value


def make_notice(category, item):
    title = first_value(item, TITLE_FIELDS)

    if not title:
        # 실제 응답의 필드명을 확인하기 위한 진단
        log(
            f"[제목 필드 없음] {category} "
            f"필드 목록: {list(item.keys())[:30]}"
        )
        return None

    notice_id = first_value(item, ID_FIELDS)
    org = first_value(item, ORG_FIELDS)
    date = first_value(item, DATE_FIELDS)
    amount = first_value(item, AMOUNT_FIELDS)
    url = first_value(item, URL_FIELDS)

    # 번호가 없을 경우 제목·기관·날짜로 중복 판별
    unique_id = (
        f"{category}|{notice_id}"
        if notice_id
        else f"{category}|{title}|{org}|{date}"
    )

    return {
        "category": category,
        "id": unique_id,
        "notice_no": notice_id,
        "title": title,
        "org": org or "미표시",
        "date": date or "미표시",
        "amount": format_amount(amount),
        "url": url
    }


# ==========================================
# 8. 텔레그램 알림
# ==========================================

def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError(
            "텔레그램 환경변수가 설정되지 않았습니다."
        )

    url = (
        f"https://api.telegram.org/"
        f"bot{BOT_TOKEN}/sendMessage"
    )

    response = requests.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "text": message,
            "disable_web_page_preview": "true"
        },
        timeout=30
    )

    response.raise_for_status()

    result = response.json()

    if not result.get("ok"):
        raise RuntimeError(
            f"텔레그램 발송 실패: "
            f"{result.get('description', '알 수 없는 오류')}"
        )


def build_message(notice):
    message = (
        "📢 나라장터 신규 용역 공고\n\n"
        f"📌 구분: {notice['category']}\n"
        f"📋 용역명: {notice['title']}\n"
        f"🏢 발주기관: {notice['org']}\n"
        f"💰 금액: {notice['amount']}\n"
        f"📅 등록일: {notice['date']}\n"
    )

    if notice["notice_no"]:
        message += (
            f"🔎 공고번호: {notice['notice_no']}\n"
        )

    if notice["url"].startswith(("https://", "http://")):
        message += f"\n🔗 {notice['url']}"

    return message


# ==========================================
# 9. 메인 실행
# ==========================================

def main():
    log("=" * 65)
    log("[시작] 나라장터 용역 모니터링")
    log(f"[현재시간] {now_kst().isoformat()}")
    log(f"[조회범위] 최근 {LOOKBACK_MINUTES}분")

    if not SERVICE_KEY:
        raise RuntimeError(
            "G2B_SERVICE_KEY 환경변수가 없습니다."
        )

    if not BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN 환경변수가 없습니다."
        )

    if not CHAT_ID:
        raise RuntimeError(
            "TELEGRAM_CHAT_ID 환경변수가 없습니다."
        )

    seen = load_seen()
    log(f"[기존 ID] {len(seen)}건")

    end_dt = now_kst()
    start_dt = end_dt - timedelta(
        minutes=LOOKBACK_MINUTES
    )

    start = start_dt.strftime("%Y%m%d%H%M")
    end = end_dt.strftime("%Y%m%d%H%M")

    log(f"[조회기간] {start} ~ {end}")

    all_notices = []
    failures = []

    for category, config in API_CONFIG.items():
        log("-" * 65)
        log(f"[{category} 조회] {start} ~ {end}")

        try:
            items = fetch_category(
                category, config, start, end
            )

            log(f"[{category}] 원본 {len(items)}건")

            matched = 0

            for item in items:
                notice = make_notice(category, item)

                if notice and is_relevant(notice["title"]):
                    all_notices.append(notice)
                    matched += 1

            log(f"[{category}] 필터 통과 {matched}건")

        except Exception as e:
            failures.append(category)
            log(f"[{category} 조회 실패] {e}")

    log("-" * 65)

    # 세 API 모두 실패하면 성공으로 처리하지 않음
    if len(failures) == len(API_CONFIG):
        raise RuntimeError(
            "발주계획·사전규격·입찰공고 "
            "API 조회가 모두 실패했습니다."
        )

    if failures:
        log(
            "[주의] 일부 API 조회 실패: "
            + ", ".join(failures)
        )

    log(f"[필터링 완료] {len(all_notices)}건")

    sent_count = 0
    checked_ids = set()

    for notice in all_notices:
        unique_id = notice["id"]

        if unique_id in seen:
            continue

        if unique_id in checked_ids:
            continue

        checked_ids.add(unique_id)

        message = build_message(notice)

        try:
            send_telegram(message)
            seen.add(unique_id)
            sent_count += 1

            # 중간에 오류가 발생해도 발송된 ID 보존
            save_seen(seen)

            log(
                f"[알림 성공] "
                f"{notice['category']} / "
                f"{notice['title']}"
            )

            time.sleep(0.5)

        except Exception as e:
            log(
                f"[텔레그램 오류] "
                f"{notice['title']}: {e}"
            )
            raise

    save_seen(seen)

    log("=" * 65)
    log(f"[완료] 신규 알림 {sent_count}건")
    log(f"[최종 ID] {len(seen)}건")
    log("=" * 65)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"[치명적 오류] {e}")
        sys.exit(1)
