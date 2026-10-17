
import os
import re
import json
import time
import sys
import hashlib
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
        "url": os.getenv("G2B_PRESPEC_URL",
            "https://apis.data.go.kr/1230000/ao/"
            "HrcspSsstndrdInfoService/"
            "getPublicPrcureThngInfoServcPPSSrch"
        ),
        "date_start": "inqryBgnDt",
        "date_end": "inqryEndDt"
