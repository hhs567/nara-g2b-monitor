import os
import json
import time
import requests
import urllib3

from bs4 import BeautifulSoup
from urllib.parse import urljoin
from datetime import datetime


# ============================================================
# SSL 경고 비활성화
# ============================================================

urllib3.disable_warnings(
    urllib3.exceptions.InsecureRequestWarning
)


# ============================================================
# 기본 설정
# ============================================================

BASE_URL = "https://www.ui4u.go.kr"

LIST_URL = (
    "https://www.ui4u.go.kr/portal/bbs/list.do"
    "?mId=0107010100&ptIdx=64"
)

SOURCE_FILE = "budget_sources.json"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


if not TELEGRAM_BOT_TOKEN:
    raise ValueError(
        "TELEGRAM_BOT_TOKEN이 설정되어 있지 않습니다."
    )

if not TELEGRAM_CHAT_ID:
    raise ValueError(
        "TELEGRAM_CHAT_ID가 설정되어 있지 않습니다."
    )


# ============================================================
# 감시 대상
# ============================================================

TARGET_YEAR = "2026"

BUDGET_KEYWORDS = [
    "추가경정예산서",
    "추가경정 예산서",
    "추경예산서",
    "추경 예산서",
]


# ============================================================
# HTTP 설정
# ============================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,*/*;q=0.8"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    "Connection": "close",
}


# ============================================================
# 웹페이지 접속
# 실패해도 프로그램 전체를 중단하지 않음
# ============================================================

def get_html(url):

    MAX_RETRIES = 4

    for attempt in range(1, MAX_RETRIES + 1):

        print(
            f"웹페이지 접속 시도 "
            f"{attempt}/{MAX_RETRIES}"
        )

        try:

            # ------------------------------------------------
            # 1차 : 정상 SSL 접속
            # ------------------------------------------------

            try:

                response = requests.get(
                    url,
                    headers=HEADERS,
                    timeout=(60, 90),
                    verify=True,
                    allow_redirects=True
                )

            except requests.exceptions.SSLError:

                print(
                    "SSL 인증서 검증 실패 "
                    "→ SSL 검증 없이 재접속"
                )

                response = requests.get(
                    url,
                    headers=HEADERS,
                    timeout=(60, 90),
                    verify=False,
                    allow_redirects=True
                )

            response.raise_for_status()

            # ------------------------------------------------
            # 한글 인코딩
            # ------------------------------------------------

            if (
                not response.encoding
                or response.encoding.lower()
                in [
                    "iso-8859-1",
                    "ascii"
                ]
            ):

                response.encoding = (
                    response.apparent_encoding
                    or "utf-8"
                )

            print(
                "웹페이지 접속 성공"
            )

            return response.text


        # ====================================================
        # 연결 시간 초과
        # ====================================================

        except requests.exceptions.ConnectTimeout:

            print(
                "연결 시간초과 발생"
            )


        # ====================================================
        # 읽기 시간 초과
        # ====================================================

        except requests.exceptions.ReadTimeout:

            print(
                "응답 대기 시간초과 발생"
            )


        # ====================================================
        # 기타 requests 오류
        # ====================================================

        except requests.exceptions.RequestException as e:

            print(
                "HTTP 접속 오류:",
                e
            )


        # ====================================================
        # 기타 오류
        # ====================================================

        except Exception as e:

            print(
                "예상하지 못한 오류:",
                e
            )


        # ====================================================
        # 마지막 시도가 아니면 대기 후 재시도
        # ====================================================

        if attempt < MAX_RETRIES:

            wait_seconds = attempt * 10

            print(
                f"{wait_seconds}초 후 재시도..."
            )

            time.sleep(
                wait_seconds
            )


    # ========================================================
    # 모든 시도 실패
    # ========================================================

    print(
        "⚠ 해당 사이트 접속 실패 "
        "→ 이번 실행에서는 건너뜁니다."
    )

    return None


# ============================================================
# 저장된 출처 불러오기
# ============================================================

def load_sources():

    try:

        with open(
            SOURCE_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

            if isinstance(
                data,
                dict
            ):
                return data

            return {}

    except FileNotFoundError:

        return {}

    except Exception as e:

        print(
            "출처파일 읽기 오류:",
            e
        )

        return {}


# ============================================================
# 출처 저장
# ============================================================

def save_sources(data):

    with open(
        SOURCE_FILE,
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
# 텔레그램
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
# 문자열 정리
# ============================================================

def normalize_text(text):

    if not text:
        return ""

    return (
        str(text)
        .replace("\xa0", " ")
        .replace("\n", " ")
        .replace("\r", " ")
        .strip()
    )


# ============================================================
# 추경예산서 제목 판별
# ============================================================

def is_budget_title(title):

    title = normalize_text(
        title
    )

    if TARGET_YEAR not in title:
        return False

    return any(
        keyword in title
        for keyword in BUDGET_KEYWORDS
    )


# ============================================================
# 추경 회차 판별
# ============================================================

def detect_budget_round(title):

    title = normalize_text(
        title
    )

    for round_number in [
        5,
        4,
        3,
        2,
        1
    ]:

        if (
            f"제{round_number}회"
            in title
        ):

            return (
                f"제{round_number}회 "
                "추가경정예산서"
            )

    return "추가경정예산서"


# ============================================================
# 목록 페이지에서 추경 게시물 찾기
# ============================================================

def find_budget_posts():

    html = get_html(
        LIST_URL
    )

    # 사이트 접속 실패
    if html is None:

        return []

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    posts = []

    for link in soup.find_all(
        "a",
        href=True
    ):

        title = normalize_text(
            link.get_text(
                " ",
                strip=True
            )
        )

        if not title:
            continue

        if not is_budget_title(
            title
        ):
            continue

        href = normalize_text(
            link.get(
                "href",
                ""
            )
        )

        if not href:
            continue

        detail_url = urljoin(
            BASE_URL,
            href
        )

        posts.append({
            "title": title,
            "detail_url": detail_url,
        })


    # ========================================================
    # 중복 제거
    # ========================================================

    unique = {}

    for post in posts:

        key = (
            post["title"]
            + "|"
            + post["detail_url"]
        )

        unique[
            key
        ] = post

    return list(
        unique.values()
    )


# ============================================================
# 상세페이지 첨부파일 찾기
# ============================================================

def find_pdf_links(detail_url):

    html = get_html(
        detail_url
    )

    if html is None:

        return []

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    files = []

    for link in soup.find_all(
        "a",
        href=True
    ):

        href = normalize_text(
            link.get(
                "href",
                ""
            )
        )

        text = normalize_text(
            link.get_text(
                " ",
                strip=True
            )
        )

        combined = (
            href
            + " "
            + text
        ).lower()

        # ----------------------------------------------------
        # 첨부파일 링크 후보
        # ----------------------------------------------------

        if not any([
            ".pdf" in combined,
            "download" in combined,
            "file" in combined,
            "atch" in combined,
            "첨부" in combined,
            "바로보기" in combined,
        ]):

            continue

        full_url = urljoin(
            detail_url,
            href
        )

        files.append({
            "name": text,
            "url": full_url,
        })


    # ========================================================
    # 중복 제거
    # ========================================================

    unique = {}

    for item in files:

        unique[
            item["url"]
        ] = item

    return list(
        unique.values()
    )


# ============================================================
# 게시물 고유 ID
# ============================================================

def make_source_id(post):

    return (
        post["title"]
        + "|"
        + post["detail_url"]
    )


# ============================================================
# 메인 실행
# ============================================================

print("=" * 70)

print(
    "의정부시 추경예산서 출처 모니터"
)

print("=" * 70)

print(
    "감시 게시판:",
    LIST_URL
)

print(
    "대상연도:",
    TARGET_YEAR
)

print()


# ============================================================
# 기존 기록
# ============================================================

sources = load_sources()


# ============================================================
# 게시물 탐색
# ============================================================

posts = find_budget_posts()


print()

print(
    "추경예산서 발견:",
    len(posts),
    "건"
)


# ============================================================
# 사이트 접속 실패 처리
# ============================================================

if not posts:

    print()
    print(
        "이번 실행에서 추경 자료를 "
        "확인하지 못했습니다."
    )

    print(
        "사이트 접속 제한 또는 "
        "신규 자료 없음 가능성"
    )

    # 기존 데이터 그대로 저장
    save_sources(
        sources
    )

    print()
    print("=" * 70)

    print(
        "기존 저장 자료:",
        len(sources),
        "건"
    )

    print(
        "프로그램 정상 종료"
    )

    print("=" * 70)

    # 중요:
    # GitHub Actions 실패로 처리하지 않고
    # 정상 종료
    exit(0)


# ============================================================
# 게시물 처리
# ============================================================

new_count = 0


for post in posts:

    source_id = make_source_id(
        post
    )

    print()
    print("-" * 70)

    print(
        "제목:",
        post["title"]
    )

    print(
        "상세:",
        post["detail_url"]
    )


    # --------------------------------------------------------
    # 상세페이지 첨부파일
    # --------------------------------------------------------

    pdf_links = find_pdf_links(
        post["detail_url"]
    )


    print(
        "첨부파일 후보:",
        len(pdf_links),
        "건"
    )


    for pdf in pdf_links:

        print(
            "첨부파일:",
            pdf.get(
                "name",
                ""
            )
        )

        print(
            "첨부 URL:",
            pdf.get(
                "url",
                ""
            )
        )


    # --------------------------------------------------------
    # 기존 확인 자료
    # --------------------------------------------------------

    if source_id in sources:

        print(
            "기존 확인 자료 "
            "→ 알림 생략"
        )

        continue


    # --------------------------------------------------------
    # 추경 회차
    # --------------------------------------------------------

    budget_round = detect_budget_round(
        post["title"]
    )


    # --------------------------------------------------------
    # 출처 저장
    # --------------------------------------------------------

    sources[
        source_id
    ] = {

        "region":
            "경기도",

        "local_government":
            "의정부시",

        "year":
            TARGET_YEAR,

        "budget_title":
            post["title"],

        "budget_round":
            budget_round,

        "detail_url":
            post["detail_url"],

        "pdf_files":
            pdf_links,

        "detected_at":
            datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
    }


    # --------------------------------------------------------
    # Telegram 메시지
    # --------------------------------------------------------

    message = (
        "📑 [신규 추경예산서 발견]\n\n"

        "📍 경기도 의정부시\n\n"

        f"📌 {post['title']}\n\n"

        f"🔎 구분 : "
        f"{budget_round}\n\n"

        "🔗 예산서 게시물\n"
        f"{post['detail_url']}"
    )


    if pdf_links:

        message += (
            "\n\n"
            "📄 첨부 예산서 확인됨"
        )

        first_pdf = (
            pdf_links[0]
        )

        file_name = first_pdf.get(
            "name",
            ""
        )

        file_url = first_pdf.get(
            "url",
            ""
        )

        if file_name:

            message += (
                "\n"
                f"{file_name}"
            )

        if file_url:

            message += (
                "\n"
                f"{file_url}"
            )

    else:

        message += (
            "\n\n"
            "⚠ 첨부파일은 "
            "자동 확인하지 못했습니다."
        )


    # --------------------------------------------------------
    # Telegram 전송
    # --------------------------------------------------------

    try:

        send_telegram(
            message
        )

        print(
            "텔레그램 전송 완료"
        )

        new_count += 1


    except Exception as e:

        print(
            "텔레그램 전송 실패:",
            e
        )


# ============================================================
# 저장
# ============================================================

save_sources(
    sources
)


# ============================================================
# 결과
# ============================================================

print()
print("=" * 70)

print(
    "신규 추경예산서:",
    new_count,
    "건"
)

print(
    "저장된 출처:",
    len(sources),
    "건"
)

print(
    "모니터 정상 종료"
)

print("=" * 70)
