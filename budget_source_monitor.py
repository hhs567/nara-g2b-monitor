import os
import json
import time
import requests
import urllib3

from bs4 import BeautifulSoup
from urllib.parse import urljoin
from datetime import datetime


# ============================================================
# SSL 경고 숨김
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
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}


# ============================================================
# 웹페이지 접속
# ============================================================

def get_html(url):

    for attempt in range(1, 4):

        try:

            print(
                f"웹페이지 접속 {attempt}/3"
            )

            try:

                # ------------------------------------------------
                # 1차: 정상 SSL 검증
                # ------------------------------------------------

                response = requests.get(
                    url,
                    headers=HEADERS,
                    timeout=30,
                    verify=True
                )

            except requests.exceptions.SSLError:

                # ------------------------------------------------
                # 의정부시 홈페이지처럼
                # GitHub Actions에서 인증서 체인 검증이
                # 실패하는 경우에만 SSL 검증 없이 재접속
                # ------------------------------------------------

                print(
                    "SSL 인증서 검증 실패 "
                    "→ SSL 검증 없이 재접속"
                )

                response = requests.get(
                    url,
                    headers=HEADERS,
                    timeout=30,
                    verify=False
                )

            response.raise_for_status()

            # ------------------------------------------------
            # 한글 인코딩 처리
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

            return response.text

        except Exception as e:

            print(
                "접속 오류:",
                e
            )

            if attempt == 3:
                raise

            time.sleep(5)

    return ""


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
# 텔레그램 전송
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
# 제목 정리
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
# 추경예산서 여부
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

    if "제5회" in title:
        return "제5회 추가경정예산서"

    if "제4회" in title:
        return "제4회 추가경정예산서"

    if "제3회" in title:
        return "제3회 추가경정예산서"

    if "제2회" in title:
        return "제2회 추가경정예산서"

    if "제1회" in title:
        return "제1회 추가경정예산서"

    return "추가경정예산서"


# ============================================================
# 목록에서 추경 게시물 찾기
# ============================================================

def find_budget_posts():

    html = get_html(
        LIST_URL
    )

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

        href = link.get(
            "href",
            ""
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

    # --------------------------------------------------------
    # 중복 제거
    # --------------------------------------------------------

    unique = {}

    for post in posts:

        key = (
            post["title"]
            + "|"
            + post["detail_url"]
        )

        unique[key] = post

    return list(
        unique.values()
    )


# ============================================================
# 상세페이지에서 첨부파일 후보 찾기
# ============================================================

def find_pdf_links(detail_url):

    html = get_html(
        detail_url
    )

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
        # PDF 또는 파일 다운로드 링크 추정
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

    # --------------------------------------------------------
    # 중복 제거
    # --------------------------------------------------------

    unique = {}

    for item in files:

        unique[
            item["url"]
        ] = item

    return list(
        unique.values()
    )


# ============================================================
# 게시물 고유 ID 생성
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
print("의정부시 추경예산서 출처 모니터")
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
# 기존 기록 불러오기
# ============================================================

sources = load_sources()


# ============================================================
# 추경 게시물 찾기
# ============================================================

posts = find_budget_posts()

print(
    "추경예산서 발견:",
    len(posts),
    "건"
)


# ============================================================
# 게시물별 처리
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
    # 상세페이지 첨부파일 확인
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
            "첨부파일명:",
            pdf["name"]
        )

        print(
            "첨부 URL:",
            pdf["url"]
        )


    # --------------------------------------------------------
    # 이미 확인한 게시물
    # --------------------------------------------------------

    if source_id in sources:

        print(
            "기존 확인 자료 → 알림 생략"
        )

        continue


    # --------------------------------------------------------
    # 추경 회차
    # --------------------------------------------------------

    budget_round = detect_budget_round(
        post["title"]
    )


    # --------------------------------------------------------
    # 신규 출처 저장
    # --------------------------------------------------------

    sources[source_id] = {

        "region": "경기도",

        "local_government": "의정부시",

        "year": TARGET_YEAR,

        "budget_title": post[
            "title"
        ],

        "budget_round": budget_round,

        "detail_url": post[
            "detail_url"
        ],

        "pdf_files": pdf_links,

        "detected_at": datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
    }


    # --------------------------------------------------------
    # 텔레그램 메시지
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


    # --------------------------------------------------------
    # 첨부파일 표시
    # --------------------------------------------------------

    if pdf_links:

        message += (
            "\n\n📄 첨부파일 확인됨"
        )

        # 첫 번째 파일만 메시지에 표시
        first_pdf = pdf_links[0]

        if first_pdf.get(
            "name"
        ):

            message += (
                "\n"
                f"{first_pdf['name']}"
            )

        if first_pdf.get(
            "url"
        ):

            message += (
                "\n"
                f"{first_pdf['url']}"
            )

    else:

        message += (
            "\n\n⚠ 첨부파일 링크를 "
            "자동 확인하지 못했습니다."
        )


    # --------------------------------------------------------
    # 텔레그램 발송
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
# 결과 저장
# ============================================================

save_sources(
    sources
)


# ============================================================
# 종료
# ============================================================

print()
print("=" * 70)

print(
    "신규 추경예산서:",
    new_count,
    "건"
)

print(
    "저장된 예산서 출처:",
    len(sources),
    "건"
)

print("모니터 종료")

print("=" * 70)
