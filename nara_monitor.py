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
