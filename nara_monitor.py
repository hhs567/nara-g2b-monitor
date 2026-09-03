import os
import json
import time
import hashlib
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import unquote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

KEYWORDS = [
    "계획", "설계", "정비", "구상", "타당성", "지정", "재생", "조성",
    "시행", "개발", "검토", "후보지", "전략", "조사", "사업화"
]


# 2차 필터 V3: 제목(용역명) 중심 정밀 분류
A_GRADE_KEYWORDS = [
    "도시기본계획", "도시관리계획", "지구단위계획", "도시개발",
    "도시재생", "도시정비", "정비사업", "재개발", "재건축",
    "공공주택", "주택지구", "택지개발", "신도시", "역세권개발",
    "산업단지", "산업입지", "경제자유구역", "개발제한구역",
    "노후계획도시", "도시계획시설", "토지이용계획"
]

B_CONTEXT_KEYWORDS = [
    "도시", "지역", "공간", "생활권", "역세권", "산업",
    "주거", "개발", "계획", "입지", "토지이용", "원도심",
    "특구", "스마트도시", "스마트시티", "수변", "워터프론트"
]

B_TOPIC_KEYWORDS = [
    "기본구상", "마스터플랜", "타당성", "타당성조사",
    "입지분석", "입지선정", "후보지", "개발수요", "개발규모",
    "광역교통", "교통계획", "환승센터", "지하화",
    "도로", "철도", "공원", "녹지", "기반시설",
    "탄소중립", "기후변화", "친환경"
]

HARD_EXCLUDE_KEYWORDS = [
    "폐기물", "건설폐기물", "생활폐기물", "청소", "환경미화",
    "채용", "인력파견", "위탁교육", "직원교육", "행사", "축제",
    "홍보", "광고", "마케팅", "영상제작", "홈페이지", "웹사이트",
    "소프트웨어", "서버", "유지보수", "전산장비", "장비구매",
    "물품구매", "제품개발", "인증제품", "식품", "의료", "임상",
    "건강검진", "보험", "경비용역", "방역", "소독", "세탁",
    "급식", "운송"
]

CORE_OVERRIDE_KEYWORDS = [
    "도시기본계획", "도시관리계획", "지구단위계획", "도시개발",
    "도시재생", "공공주택", "주택지구", "산업단지", "산업입지",
    "역세권", "개발제한구역", "노후계획도시", "토지이용계획",
    "경제자유구역"
]

SEOUL = ZoneInfo("Asia/Seoul")

API_SPECS = [
    {
        "label": "발주계획",
        "base": "https://apis.data.go.kr/1230000/ao/OrderPlanSttusService",
        "op": "getOrderPlanSttusListServc",
        "key_env": "G2B_ORDERPLAN_KEY",
    },
    {
        "label": "사전규격",
        "base": "https://apis.data.go.kr/1230000/ao/HrcspSsstndrdInfoService",
        "op": "getPublicPrcureThngInfoServc",
        "key_env": "G2B_PRESPEC_KEY",
    },
    {
        "label": "입찰공고",
        "base": "https://apis.data.go.kr/1230000/ad/BidPublicInfoService",
        "op": "getBidPblancListInfoServc",
        "key_env": "G2B_BID_KEY",
    },
]

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

LOOKBACK_MINUTES = int(os.environ.get("LOOKBACK_MINUTES", "30"))
NUM_OF_ROWS = int(os.environ.get("NUM_OF_ROWS", "1000"))
STATE_FILE = os.environ.get("STATE_FILE", "seen_ids.json")
STATE_MAX_AGE_DAYS = int(os.environ.get("STATE_MAX_AGE_DAYS", "30"))

CONNECT_TIMEOUT = int(os.environ.get("CONNECT_TIMEOUT", "30"))
READ_TIMEOUT = int(os.environ.get("READ_TIMEOUT", "60"))
API_RETRIES = int(os.environ.get("API_RETRIES", "2"))
RETRY_BACKOFF = int(os.environ.get("RETRY_BACKOFF", "3"))


def now_seoul():
    return datetime.now(SEOUL)


def build_session():
    retry = Retry(
        total=API_RETRIES,
        connect=API_RETRIES,
        read=API_RETRIES,
        status=API_RETRIES,
        backoff_factor=RETRY_BACKOFF,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(["GET", "POST"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


SESSION = build_session()


def load_state():
    path = Path(STATE_FILE)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_state(state):
    Path(STATE_FILE).write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def cleanup_state(state):
    cutoff = now_seoul() - timedelta(days=STATE_MAX_AGE_DAYS)
    cleaned = {}
    for key, ts in state.items():
        try:
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=SEOUL)
            if dt >= cutoff:
                cleaned[key] = ts
        except Exception:
            pass
    return cleaned


def flatten(obj, prefix=""):
    parts = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            parts.extend(flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            parts.extend(flatten(v, f"{prefix}[{i}]"))
    else:
        parts.append((prefix, "" if obj is None else str(obj)))
    return parts


def record_text(record):
    return " ".join(v for _, v in flatten(record)).lower()


def matched_keywords(record):
    """1차 키워드도 제목(용역명)을 중심으로 검색합니다."""
    title = auto_find_title(record)
    if not title or title == "(용역명 확인 필요)":
        return []
    lower_title = title.lower()
    return [kw for kw in KEYWORDS if kw.lower() in lower_title]


def _normalize_title_for_match(title):
    return (
        title.replace(" ", "")
             .replace("·", "")
             .replace("-", "")
             .replace("_", "")
             .lower()
    )


def _hits_in_title(title, keywords):
    norm = _normalize_title_for_match(title)
    hits = []
    for kw in keywords:
        nkw = _normalize_title_for_match(kw)
        if nkw and nkw in norm:
            hits.append(kw)
    return hits


def classify_record(record):
    """
    V3 정밀 분류:
    A급 = 도시계획 핵심 업무가 제목에 직접 포함
    B급 = 도시/개발/계획 등 맥락어 + 도로/철도/타당성 등 주제어가 함께 포함
    제외 = 채용/폐기물/행사 등 비관련 또는 도시계획 맥락 부족
    """
    title = auto_find_title(record)
    if not title or title == "(용역명 확인 필요)":
        return "EXCLUDE", [], []

    a_hits = _hits_in_title(title, A_GRADE_KEYWORDS)
    exclude_hits = _hits_in_title(title, HARD_EXCLUDE_KEYWORDS)
    override_hits = _hits_in_title(title, CORE_OVERRIDE_KEYWORDS)

    if a_hits:
        return "A", a_hits, exclude_hits

    if exclude_hits and not override_hits:
        return "EXCLUDE", [], exclude_hits

    context_hits = _hits_in_title(title, B_CONTEXT_KEYWORDS)
    topic_hits = _hits_in_title(title, B_TOPIC_KEYWORDS)

    if context_hits and topic_hits:
        combined = []
        for x in context_hits + topic_hits:
            if x not in combined:
                combined.append(x)
        return "B", combined, exclude_hits

    strong_b = _hits_in_title(title, [
        "지역계획", "광역계획", "공간계획", "생활권계획",
        "스마트도시", "스마트시티", "원도심활성화",
        "투자선도지구", "기회발전특구", "평화경제특구",
        "기업도시", "복합개발"
    ])
    if strong_b:
        return "B", strong_b, exclude_hits

    return "EXCLUDE", [], exclude_hits


def get_first(record, candidates):
    if not isinstance(record, dict):
        return ""
    for key in candidates:
        val = record.get(key)
        if val not in (None, ""):
            return str(val).strip()
    return ""


def auto_find_title(record):
    """
    실제 용역명/사업명을 우선 선택합니다.
    N/Y, 신규(단기), 코드값처럼 제목이 아닌 짧은 값을 자동 제외합니다.
    """
    if not isinstance(record, dict):
        return ""

    bad_values = {
        "N", "Y", "n", "y",
        "신규", "신규(단기)", "신규(장기)", "계속", "변경", "취소",
        "용역", "일반용역", "기술용역", "기타용역"
    }

    def valid_title(s):
        if s is None:
            return False
        s = str(s).strip()
        if s in bad_values:
            return False
        if len(s) < 5:
            return False
        if s.isdigit():
            return False
        if s.lower().startswith(("http://", "https://")):
            return False
        return True

    # 나라장터에서 용역명/공고명으로 사용될 가능성이 높은 필드
    # 공고/규격/사업명 계열을 제품명 계열보다 우선합니다.
    explicit = [
        "bidNtceNm", "bfSpecNm", "bfSpecRgstNm",
        "publicPrcureThngNm", "orderPlanNm",
        "bsnsNm", "bizNm", "projectNm", "taskNm",
        "servcNm", "serviceNm", "srvceNm",
        "cntrctNm", "ntceNm", "noticeNm",
        "prdctDtlNm", "prdctNm", "itemNm", "goodsNm", "title"
    ]

    for key in explicit:
        value = record.get(key)
        if valid_title(value):
            return str(value).strip()

    # 예상 필드명이 없으면 레코드 전체에서 제목다운 문자열을 점수화합니다.
    candidates = []
    for key, value in record.items():
        if not valid_title(value):
            continue

        s = str(value).strip()
        k = str(key).lower()

        # 제목으로 쓰면 안 되는 메타데이터
        if any(tok in k for tok in [
            "instt", "agency", "org", "dept", "user", "charger",
            "tel", "fax", "email", "addr", "date", "dt",
            "code", "cd", "id", "url", "amount", "amt",
            "price", "prce", "budget", "bdgt",
            "yn", "flag", "status"
        ]):
            continue

        score = 0

        # 필드명 자체가 공고명/사업명/용역명 계열이면 최우선
        if any(tok in k for tok in [
            "ntcenm", "specnm", "bsnsnm", "biznm", "projectnm",
            "tasknm", "servcnm", "servicenm", "srvcenm",
            "cntrctnm", "noticenm", "title"
        ]):
            score += 150

        # 실제 문자열 내용이 용역명답다면 가점
        if "용역" in s:
            score += 100

        for word in [
            "계획", "설계", "정비", "구상", "타당성", "지정", "재생",
            "조성", "시행", "개발", "검토", "후보지", "전략", "조사",
            "사업화", "도시", "산업단지", "공공주택", "역세권"
        ]:
            if word in s:
                score += 20

        if any("가" <= ch <= "힣" for ch in s):
            score += 10

        # 지나치게 짧은 값보다 문장형 사업명을 우선
        score += min(len(s), 120) / 4

        candidates.append((score, len(s), s))

    if candidates:
        candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return candidates[0][2]

    return "(용역명 확인 필요)"


def make_unique_key(label, record):
    preferred = [
        "orderPlanUntyNo", "bfSpecRgstNo", "bidNtceNo", "bidNtceOrd",
        "orderPlanNo", "rgstNo", "ntceNo"
    ]
    values = [label]
    for k in preferred:
        if isinstance(record, dict) and record.get(k) not in (None, ""):
            values.append(f"{k}:{record.get(k)}")
    if len(values) > 1:
        return "|".join(values)

    raw = json.dumps(record, ensure_ascii=False, sort_keys=True, default=str)
    return f"{label}|sha256:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"


def extract_records(obj):
    found = []

    def walk(x):
        if isinstance(x, dict):
            if "item" in x:
                item = x["item"]
                if isinstance(item, list):
                    found.extend([v for v in item if isinstance(v, dict)])
                elif isinstance(item, dict):
                    found.append(item)

            if "items" in x:
                items = x["items"]
                if isinstance(items, list):
                    found.extend([v for v in items if isinstance(v, dict)])
                elif isinstance(items, dict) and "item" in items:
                    item = items["item"]
                    if isinstance(item, list):
                        found.extend([v for v in item if isinstance(v, dict)])
                    elif isinstance(item, dict):
                        found.append(item)

            for v in x.values():
                if isinstance(v, (dict, list)):
                    walk(v)

        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(obj)

    uniq = []
    seen = set()
    for rec in found:
        sig = json.dumps(rec, ensure_ascii=False, sort_keys=True, default=str)
        if sig not in seen:
            seen.add(sig)
            uniq.append(rec)
    return uniq


def api_time_window():
    end = now_seoul()
    start = end - timedelta(minutes=LOOKBACK_MINUTES)
    return start, end


def request_api(spec):
    service_key = os.environ.get(spec["key_env"], "").strip()
    if not service_key:
        raise RuntimeError(f"{spec['key_env']} Secret이 없습니다.")

    service_key = unquote(service_key)

    start, end = api_time_window()
    params = {
        "serviceKey": service_key,
        "pageNo": 1,
        "numOfRows": NUM_OF_ROWS,
        "type": "json",
        "inqryDiv": "1",
        "inqryBgnDt": start.strftime("%Y%m%d%H%M"),
        "inqryEndDt": end.strftime("%Y%m%d%H%M"),
    }

    if spec["label"] == "발주계획":
        params["orderBgnYm"] = start.strftime("%Y%m")
        params["orderEndYm"] = end.strftime("%Y%m")

    url = f"{spec['base'].rstrip('/')}/{spec['op']}"

    print(
        f"[{spec['label']}] 접속 시작 "
        f"(connect={CONNECT_TIMEOUT}s, read={READ_TIMEOUT}s, retries={API_RETRIES})"
    )

    resp = SESSION.get(
        url,
        params=params,
        timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
    )

    print(f"[{spec['label']}] HTTP {resp.status_code}")

    if not resp.ok:
        raise RuntimeError(
            f"{spec['label']} API HTTP 오류 {resp.status_code}: "
            f"{resp.text[:300]}"
        )

    try:
        data = resp.json()
    except Exception:
        raise RuntimeError(
            f"{spec['label']} API가 JSON을 반환하지 않았습니다. "
            f"응답 앞부분: {resp.text[:300]}"
        )

    return extract_records(data)


def format_amount(value):
    if not value:
        return ""
    s = str(value).replace(",", "").strip()
    try:
        n = float(s)
        return f"{n:,.0f}원"
    except Exception:
        return str(value)


def format_message(label, record, kws, grade, field_hits):
    title = auto_find_title(record) or "(제목 확인 필요)"

    inst = get_first(record, [
        "ntceInsttNm", "orderInsttNm", "dmndInsttNm",
        "rlDminsttNm", "insttNm", "dminsttNm"
    ])

    amount = get_first(record, [
        "asignBdgtAmt", "presmptPrce", "bsnsSumAmt",
        "orderAmt", "bdgtAmt"
    ])

    date_val = get_first(record, [
        "bidNtceDt", "rgstDt", "orderPlanDt", "bfSpecRgstDt",
        "ntceDt", "writngDt", "orderPlanRegDt"
    ])

    url = get_first(record, [
        "bidNtceDtlUrl", "bfSpecDtlUrl", "orderPlanUrl",
        "ntceDtlUrl", "url"
    ])

    grade_icon = "🔴" if grade == "A" else "🟡"
    lines = [
        f"{grade_icon} [{grade}급/나라장터 {label}]",
        title,
        "",
        f"🏢 발주기관: {inst or '-'}",
        f"🔎 1차 검색어: {', '.join(kws)}",
        f"🏙 2차 분야: {', '.join(field_hits[:6]) if field_hits else '-'}",
    ]

    if amount:
        lines.append(f"💰 금액: {format_amount(amount)}")
    if date_val:
        lines.append(f"🕒 등록/공고일: {date_val}")
    if url:
        lines.extend(["", f"🔗 {url}"])

    return "\n".join(lines)


def send_telegram(text):
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN Secret이 없습니다.")
    if not TELEGRAM_CHAT_ID:
        raise RuntimeError("TELEGRAM_CHAT_ID Secret이 없습니다.")

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
    }

    resp = SESSION.post(
        url,
        json=payload,
        timeout=(30, 60),
    )

    if not resp.ok:
        raise RuntimeError(
            f"Telegram 전송 실패: HTTP {resp.status_code}, {resp.text[:300]}"
        )


def main():
    state = cleanup_state(load_state())
    new_count = 0
    errors = []

    print(f"[시작] {now_seoul().isoformat()}")
    print(f"[조회범위] 최근 {LOOKBACK_MINUTES}분")
    print(f"[키워드] {', '.join(KEYWORDS)}")

    for spec in API_SPECS:
        label = spec["label"]

        try:
            records = request_api(spec)
            print(f"[{label}] 수신 레코드: {len(records)}")

            for record in records:
                # 1차 필터
                kws = matched_keywords(record)
                if not kws:
                    continue

                # 2차 필터 + A/B 등급
                grade, field_hits, exclude_hits = classify_record(record)
                if grade == "EXCLUDE":
                    print(
                        f"[{label}] 2차 필터 제외 "
                        f"(1차={','.join(kws)}, 제외={','.join(exclude_hits) or '-'})"
                    )
                    continue

                uid = make_unique_key(label, record)
                if uid in state:
                    continue

                message = format_message(label, record, kws, grade, field_hits)
                send_telegram(message)

                state[uid] = now_seoul().isoformat()
                save_state(state)
                new_count += 1
                print(
                    f"[{label}] {grade}급 새 알림 전송 완료 "
                    f"(분야={','.join(field_hits[:6])})"
                )
                time.sleep(0.5)

        except Exception as e:
            errors.append(f"{label}: {e}")
            print(f"[오류] {label}: {e}")

    state = cleanup_state(state)
    save_state(state)

    print(f"[완료] 신규 알림 {new_count}건")

    if errors:
        print("[경고] 일부 API 조회가 실패했습니다.")
        for err in errors:
            print(" -", err)

        # 핵심 변경점:
        # 일부 API가 일시적으로 실패해도 전체 Workflow를 실패 처리하지 않음.
        # 다음 예약 실행에서 다시 시도합니다.
        print("[종료] 다음 실행에서 실패한 API를 다시 시도합니다.")


if __name__ == "__main__":
    main()
