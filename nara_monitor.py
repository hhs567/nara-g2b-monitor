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

CONNECT_TIMEOUT = int(os.environ.get("CONNECT_TIMEOUT", "120"))
READ_TIMEOUT = int(os.environ.get("READ_TIMEOUT", "120"))
API_RETRIES = int(os.environ.get("API_RETRIES", "3"))
RETRY_BACKOFF = int(os.environ.get("RETRY_BACKOFF", "10"))


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
    text = record_text(record)
    return [kw for kw in KEYWORDS if kw.lower() in text]


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
    용역명/사업명을 우선 선택합니다.
    '신규(단기)', '신규(장기)' 같은 발주구분 값은 제목으로 사용하지 않습니다.
    """
    if not isinstance(record, dict):
        return ""

    generic_values = {
        "신규(단기)", "신규(장기)", "신규", "계속", "변경", "취소",
        "용역", "일반용역", "기술용역", "기타용역"
    }

    # 1) 용역명/사업명으로 쓰일 가능성이 높은 필드를 최우선
    explicit = [
        "servcNm", "serviceNm", "srvceNm",
        "bsnsNm", "bizNm", "projectNm", "taskNm",
        "bidNtceNm", "bfSpecNm", "prdctNm",
        "orderPlanNm", "cntrctNm", "ntceNm",
        "publicPrcureThngNm", "prdctDtlNm",
        "itemNm", "goodsNm", "title"
    ]

    for key in explicit:
        val = record.get(key)
        if val not in (None, ""):
            s = str(val).strip()
            if s and s not in generic_values:
                return s

    # 2) 실제 값에 '용역'이 포함된 문자열을 강하게 우선
    service_candidates = []
    for key, value in record.items():
        if value in (None, "") or not isinstance(value, (str, int, float)):
            continue

        s = str(value).strip()
        if not s or s in generic_values:
            continue

        k = str(key).lower()

        # 기관명/코드/일자/금액/URL 등은 제목 후보에서 제외
        if any(tok in k for tok in [
            "instt", "agency", "org", "dept", "user", "charger",
            "tel", "fax", "email", "addr", "date", "dt",
            "code", "cd", "id", "url", "amount", "amt",
            "price", "prce", "budget", "bdgt",
            "se", "div", "type", "kind", "cl", "status"
        ]):
            continue

        score = 0

        if "용역" in s:
            score += 100
        if any(word in s for word in [
            "계획", "설계", "정비", "구상", "타당성", "재생",
            "조성", "개발", "검토", "전략", "조사", "사업화"
        ]):
            score += 30

        if any(tok in k for tok in [
            "servc", "service", "srvce", "bsns", "biz",
            "project", "task", "prdct", "item", "cntrct",
            "ntce", "notice", "name", "nm", "title"
        ]):
            score += 20

        # 실제 용역명은 보통 짧은 구분값보다 길다.
        score += min(len(s), 100) / 5

        if score > 0:
            service_candidates.append((score, len(s), s))

    if service_candidates:
        service_candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return service_candidates[0][2]

    # 3) 마지막 보루: '신규(단기)' 등 제외 후 가장 긴 한글 문자열
    fallback = []
    for value in record.values():
        if isinstance(value, str):
            s = value.strip()
            if (
                len(s) >= 8
                and s not in generic_values
                and "http" not in s.lower()
                and any("가" <= ch <= "힣" for ch in s)
            ):
                fallback.append(s)

    if fallback:
        return max(fallback, key=len)

    return ""


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


def format_message(label, record, kws):
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

    lines = [
        f"🔔 [나라장터 {label}]",
        title,
        "",
        f"🏢 발주기관: {inst or '-'}",
        f"🔎 검색어: {', '.join(kws)}",
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
                kws = matched_keywords(record)
                if not kws:
                    continue

                uid = make_unique_key(label, record)
                if uid in state:
                    continue

                message = format_message(label, record, kws)
                send_telegram(message)

                state[uid] = now_seoul().isoformat()
                save_state(state)
                new_count += 1
                print(f"[{label}] 새 알림 전송 완료")
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
