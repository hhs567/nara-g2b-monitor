            if not isinstance(data.get("response"), dict) or not isinstance(data["response"].get("body"), dict):
                raise ValueError(f"예상과 다른 API 응답 구조: {str(data)[:350]}")

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
    "orderPlanSj",
    "orderPlanTitle",
    "bizNm",
    "bizName",
    "orderPlanName",
    "bsnsNm",
    "prdctClsfcNoNm",
    "prdctNm",
    "bfSpecNm",
    "bfSpecRgstNm",
    "publicPrcureThngNm",
    "prdctClsfcNoNm",
    "preSpecNm",
    "bidNtceNm",
    "bidNtceName",
    "bidPblancNm",
    "ntceNm",
    "servcNm",
    "cntrctNm",
    "prcrmntNm",
    "pblancNm"
]

ID_FIELDS = [
    "orderPlanNo",
    "orderPlanUntyNo",
    "orderPlanRegNo",
    "bfSpecRgstNo",
    "bfSpecRgstNoSeq",
    "preSpecRgstNo",
    "bidNtceNo",
    "bidPblancNo",
    "ntceNo",
    "rgstNo"
]

ORG_FIELDS = [
    "ntceInsttNm",
    "dminsttCdNm",
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
    "asignBdgtAmnt",
    "asignBdgt",
    "bdgtAmt",
    "presmptPrce",
    "presmptPrceAmt",
    "orderPlanAmt"
]

URL_FIELDS = [
    "bidNtceDtlUrl",
    "bfSpecDtlUrl",
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
            f"필드 목록: {list(item.keys())[:45]}"
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
