#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
나라장터 설계관련 용역 모니터링
- 발주계획
- 사전규격
- 입찰공고
를 조회한 뒤 15개 키워드가 포함된 항목을 Telegram으로 알립니다.

필수 환경변수
  G2B_ORDERPLAN_KEY : 발주계획 API 인증키
  G2B_PRESPEC_KEY   : 사전규격 API 인증키
  G2B_BID_KEY       : 입찰공고 API 인증키
  TELEGRAM_BOT_TOKEN
  TELEGRAM_CHAT_ID

선택 환경변수
  LOOKBACK_MINUTES=30
  NUM_OF_ROWS=1000
  KEYWORD_MATCH_MODE=any
"""

import html
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import unquote

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("nara-monitor")

KEYWORDS = [
    "계획", "설계", "정비", "구상", "타당성",
    "지정", "재생", "조성", "시행", "개발",
    "검토", "후보지", "전략", "조사", "사업화",
]

ORDERPLAN_URL = "https://apis.data.go.kr/1230000/ao/OrderPlanSttusService"
ORDERPLAN_OP = "getOrderPlanSttusListServc"

PRESPEC_URL = "https://apis.data.go.kr/1230000/ao/HrcspSsstndrdInfoService"
PRESPEC_OP = "getPublicPrcureThngInfoServc"

BID_URL = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService"
BID_OP = "getBidPblancListInfoServc"

G2B_HOME = "https://www.g2b.go.kr/"

TIMEOUT = 30
MAX_TELEGRAM_LEN = 3900


def env(name: str, required: bool = True, default: str = "") -> str:
    value = os.getenv(name, default).strip()
    if required and not value:
        raise RuntimeError(f"환경변수 {name}가 없습니다.")
    return value


def decode_service_key(key: str) -> str:
    # data.go.kr 화면에서 복사한 Encoding 키(%2F, %3D 등)와
    # Decoding 키를 모두 받아들이기 위해 한 번만 URL-decode합니다.
    return unquote(key.strip())


def now_local() -> datetime:
    # GitHub Actions는 UTC에서 동작하므로 한국 시간 기준으로 명시합니다.
    return datetime.utcnow() + timedelta(hours=9)


def dt14(dt: datetime) -> str:
    return dt.strftime("%Y%m%d%H%M")


def dt12(dt: datetime) -> str:
    return dt.strftime("%Y%m%d%H%M")


def ym(dt: datetime) -> str:
    return dt.strftime("%Y%m")


def request_json(
    base_url: str,
    operation: str,
    service_key: str,
    params: Dict[str, Any],
    label: str,
) -> Any:
    query = dict(params)
    query["serviceKey"] = decode_service_key(service_key)

    url = base_url.rstrip("/") + "/" + operation
    log.info("%s API 요청: %s", label, url)

    last_error = None
    for attempt in range(1, 4):
        try:
            r = requests.get(url, params=query, timeout=TIMEOUT)
            r.raise_for_status()
            text = r.text.strip()

            if not text:
                raise RuntimeError("빈 응답")

            try:
                return r.json()
            except ValueError:
                # 혹시 XML이 반환되더라도 에러 내용을 확인할 수 있게 앞부분을 남김
                raise RuntimeError(f"JSON이 아닌 응답: {text[:500]}")
        except Exception as e:
            last_error = e
            log.warning("%s API 오류 (%d/3): %s", label, attempt, e)
            if attempt < 3:
                time.sleep(2 * attempt)

    raise RuntimeError(f"{label} API 호출 실패: {last_error}")


def unwrap_items(payload: Any) -> List[Dict[str, Any]]:
    """
    나라장터 API의 JSON 구조가 서비스별/버전별로 조금 달라질 수 있으므로
    response.body.items.item / body.items / items / item 등을 폭넓게 처리합니다.
    """
    if payload is None:
        return []

    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]

    if not isinstance(payload, dict):
        return []

    response = payload.get("response", payload)
    body = response.get("body", response) if isinstance(response, dict) else response

    if isinstance(body, dict):
        items = body.get("items")
        if isinstance(items, dict):
            item = items.get("item")
            if item is None:
                return []
            if isinstance(item, list):
                return [x for x in item if isinstance(x, dict)]
            if isinstance(item, dict):
                return [item]
        elif isinstance(items, list):
            return [x for x in items if isinstance(x, dict)]

        item = body.get("item")
        if isinstance(item, list):
            return [x for x in item if isinstance(x, dict)]
        if isinstance(item, dict):
            return [item]

    return []


def get_header(payload: Any, name: str, default: str = "") -> str:
    if not isinstance(payload, dict):
        return default
    response = payload.get("response", payload)
    if not isinstance(response, dict):
        return default
    header = response.get("header", {})
    if not isinstance(header, dict):
        return default
    return str(header.get(name, default))


def scalar_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return ""
    return str(value).strip()


def first_value(item: Dict[str, Any], keys: Iterable[str]) -> str:
    for key in keys:
        if key in item:
            value = scalar_text(item[key])
            if value:
                return value
    return ""


def flatten_text(value: Any) -> str:
    parts: List[str] = []

    def walk(v: Any) -> None:
        if isinstance(v, dict):
            for k, val in v.items():
                # URL은 키워드 검색에 필요 없으므로 제외
                if "url" not in k.lower():
                    walk(val)
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif v is not None:
            s = str(v).strip()
            if s:
                parts.append(s)

    walk(value)
    return " ".join(parts)


def matched_keywords(item: Dict[str, Any]) -> List[str]:
    text = flatten_text(item)
    return [kw for kw in KEYWORDS if kw in text]


def clean_text(value: str, max_len: int = 220) -> str:
    value = html.unescape(re.sub(r"\s+", " ", value or "")).strip()
    if len(value) > max_len:
        return value[: max_len - 1] + "…"
    return value


def find_url(item: Dict[str, Any]) -> str:
    preferred = [
        "bidNtceUrl", "bidNtceUrl2", "bidNtceUrl3",
        "bfSpecUrl", "specUrl", "detailUrl", "url",
    ]
    for key in preferred:
        if key in item:
            value = scalar_text(item[key])
            if value.startswith("http"):
                return value

    # 혹시 URL 필드명이 바뀐 경우
    for key, value in item.items():
        if "url" in key.lower():
            v = scalar_text(value)
            if v.startswith("http"):
                return v
    return ""


def normalize_record(kind: str, item: Dict[str, Any]) -> Dict[str, str]:
    if kind == "입찰공고":
        title = first_value(item, [
            "bidNtceNm", "bidNtceNmInfo", "bidNtceTitle",
            "bidNtceName", "ntceNm",
        ])
        number = first_value(item, ["bidNtceNo", "bidNtceNoList"])
        agency = first_value(item, [
            "ntceInsttNm", "orderInsttNm", "dminsttNm",
            "rlsBidUnms", "orderInsttName",
        ])
        reg_dt = first_value(item, ["bidNtceDt", "rgstDt", "ntceDt"])
        close_dt = first_value(item, [
            "bidClseDt", "bidClseDtTm", "bidClseDt2",
        ])
        detail = first_value(item, [
            "bidNtceDtlUrl", "bidNtceNm", "srvceDivNm",
        ])

    elif kind == "사전규격":
        title = first_value(item, [
            "bfSpecNm", "prdctClsfcNoNm", "specNm",
            "bidNtceNm", "orderPlanNm",
        ])
        number = first_value(item, ["bfSpecRgstNo", "bfSpecNo"])
        agency = first_value(item, [
            "orderInsttNm", "orderInsttName", "ntceInsttNm",
        ])
        reg_dt = first_value(item, [
            "bfSpecRgstDt", "bfSpecRgstDttm", "rgstDt",
        ])
        close_dt = first_value(item, [
            "bfSpecClseDt", "bfSpecClseDtTm", "bfSpecEndDt",
        ])
        detail = first_value(item, ["bfSpecNm", "prdctClsfcNoNm"])

    else:
        title = first_value(item, [
            "orderPlanNm", "orderPlanName", "bfSpecNm",
            "bidNtceNm", "orderPlanUntNo",
        ])
        number = first_value(item, [
            "orderPlanUntNo", "orderPlanNo",
        ])
        agency = first_value(item, [
            "orderInsttNm", "orderInsttName", "orderInsttCd",
        ])
        reg_dt = first_value(item, [
            "orderPlanRegDt", "rgstDt", "orderPlanDt",
        ])
        close_dt = first_value(item, [
            "orderEndDt", "orderEndYmd", "orderEndYm",
        ])
        detail = first_value(item, ["orderPlanNm", "orderPlanUntNo"])

    return {
        "kind": kind,
        "title": clean_text(title or "(제목 확인 필요)"),
        "number": clean_text(number, 100),
        "agency": clean_text(agency, 120),
        "reg_dt": clean_text(reg_dt, 50),
        "close_dt": clean_text(close_dt, 50),
        "detail": clean_text(detail, 220),
        "url": find_url(item),
    }


def record_key(record: Dict[str, str], item: Dict[str, Any]) -> str:
    number = record.get("number", "")
    if number:
        return f"{record['kind']}|{number}"
    # 번호가 없는 경우 주요 값으로 해시 대용 키 생성
    raw = "|".join([
        record.get("kind", ""),
        record.get("agency", ""),
        record.get("title", ""),
        record.get("reg_dt", ""),
        flatten_text(item)[:300],
    ])
    return raw


def fetch_bid(key: str, start: datetime, end: datetime) -> List[Dict[str, Any]]:
    payload = request_json(
        BID_URL, BID_OP, key,
        {
            "pageNo": 1,
            "numOfRows": int(os.getenv("NUM_OF_ROWS", "1000")),
            "type": "json",
            "inqryDiv": "1",
            "inqryBgnDt": dt14(start),
            "inqryEndDt": dt14(end),
        },
        "입찰공고",
    )
    return unwrap_items(payload)


def fetch_prespec(key: str, start: datetime, end: datetime) -> List[Dict[str, Any]]:
    payload = request_json(
        PRESPEC_URL, PRESPEC_OP, key,
        {
            "pageNo": 1,
            "numOfRows": int(os.getenv("NUM_OF_ROWS", "1000")),
            "inqryDiv": "1",
            "type": "json",
            "inqryBgnDt": dt14(start),
            "inqryEndDt": dt14(end),
        },
        "사전규격",
    )
    return unwrap_items(payload)


def fetch_orderplan(key: str, start: datetime, end: datetime) -> List[Dict[str, Any]]:
    payload = request_json(
        ORDERPLAN_URL, ORDERPLAN_OP, key,
        {
            "pageNo": 1,
            "numOfRows": int(os.getenv("NUM_OF_ROWS", "1000")),
            "inqryDiv": "1",
            "orderBgnYm": ym(start),
            "orderEndYm": ym(end),
            "inqryBgnDt": dt14(start),
            "inqryEndDt": dt14(end),
            "type": "json",
        },
        "발주계획",
    )
    return unwrap_items(payload)


def telegram_send(token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    r = requests.post(
        url,
        data={
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": "true",
        },
        timeout=TIMEOUT,
    )
    r.raise_for_status()


def format_message(record: Dict[str, str], keywords: List[str]) -> str:
    lines = [
        f"📢 나라장터 {record['kind']} 알림",
        "",
        f"🔎 키워드: {', '.join(keywords)}",
        f"📌 제목: {record['title']}",
    ]
    if record["number"]:
        lines.append(f"🔢 번호: {record['number']}")
    if record["agency"]:
        lines.append(f"🏢 기관: {record['agency']}")
    if record["reg_dt"]:
        lines.append(f"🕒 등록/게시: {record['reg_dt']}")
    if record["close_dt"]:
        lines.append(f"⏰ 마감/종료: {record['close_dt']}")
    if record["url"]:
        lines.extend(["", f"🔗 {record['url']}"])
    else:
        lines.extend(["", f"🔗 나라장터: {G2B_HOME}"])

    return "\n".join(lines)


STATE_FILE = os.getenv("STATE_FILE", "seen_ids.json")
STATE_MAX_AGE_DAYS = int(os.getenv("STATE_MAX_AGE_DAYS", "30"))


def load_seen_state() -> Dict[str, float]:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        cutoff = time.time() - STATE_MAX_AGE_DAYS * 86400
        return {
            str(k): float(v)
            for k, v in data.items()
            if isinstance(v, (int, float)) and float(v) >= cutoff
        }
    except FileNotFoundError:
        return {}
    except Exception as e:
        log.warning("상태파일 읽기 실패: %s", e)
        return {}


def save_seen_state(state: Dict[str, float]) -> None:
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, STATE_FILE)



def main() -> int:
    order_key = env("G2B_ORDERPLAN_KEY")
    prespec_key = env("G2B_PRESPEC_KEY")
    bid_key = env("G2B_BID_KEY")
    telegram_token = env("TELEGRAM_BOT_TOKEN")
    telegram_chat_id = env("TELEGRAM_CHAT_ID")

    lookback = int(os.getenv("LOOKBACK_MINUTES", "30"))
    end = now_local()
    start = end - timedelta(minutes=lookback)

    log.info(
        "조회기간(KST): %s ~ %s",
        dt14(start), dt14(end)
    )

    all_hits: List[tuple[str, Dict[str, str], List[str], str]] = []
    seen_state = load_seen_state()
    seen: set[str] = set(seen_state.keys())

    jobs = [
        ("발주계획", lambda: fetch_orderplan(order_key, start, end)),
        ("사전규격", lambda: fetch_prespec(prespec_key, start, end)),
        ("입찰공고", lambda: fetch_bid(bid_key, start, end)),
    ]

    for kind, fetcher in jobs:
        try:
            items = fetcher()
            log.info("%s: %d건 수신", kind, len(items))
        except Exception as e:
            # 한 API가 일시적으로 실패해도 다른 API는 계속 처리합니다.
            log.exception("%s 조회 실패: %s", kind, e)
            continue

        for item in items:
            hits = matched_keywords(item)
            if not hits:
                continue

            record = normalize_record(kind, item)
            key = record_key(record, item)
            if key in seen:
                continue
            seen.add(key)
            all_hits.append((kind, record, hits, key))

    log.info("키워드 매칭: %d건", len(all_hits))

    if not all_hits:
        # GitHub Actions 로그에서 정상 실행 여부를 확인할 수 있도록 남김
        save_seen_state(seen_state)
        log.info("새로 알릴 검색 결과가 없습니다.")
        return 0

    sent = 0
    for _, record, hits, key in all_hits:
        msg = format_message(record, hits)
        if len(msg) > MAX_TELEGRAM_LEN:
            msg = msg[: MAX_TELEGRAM_LEN - 1] + "…"
        try:
            telegram_send(telegram_token, telegram_chat_id, msg)
            seen_state[key] = time.time()
            sent += 1
            time.sleep(0.15)
        except Exception as e:
            log.exception("Telegram 전송 실패: %s", e)

    save_seen_state(seen_state)
    log.info("Telegram 전송 완료: %d/%d", sent, len(all_hits))
    return 0 if sent == len(all_hits) else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        log.exception("치명적 오류: %s", e)
        raise
