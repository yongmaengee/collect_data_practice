"""설정 모듈.

API 엔드포인트·파라미터 등 환경에 따라 달라지는 값을 코드에서 분리한다.
값은 프로젝트 루트의 .env 파일에서 읽고, 없으면 안전한 기본값을 사용한다.
(.env 는 .gitignore 로 제외하고, 형식은 .env.example 로 공유한다.)
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# 이 파일(src/config.py) 기준 상대경로로 프로젝트 루트를 계산한다.
# 어느 디렉터리에서 실행하든 동일하게 동작하도록 절대경로 대신 __file__ 기준으로 잡는다.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"
DATA_DIR = PROJECT_ROOT / "data"

# .env 가 있으면 로드한다 (없어도 오류 없이 기본값으로 동작).
load_dotenv(ENV_PATH)


def _env(key: str, default: str) -> str:
    """환경변수를 읽되, 비어 있으면 기본값을 돌려준다."""
    value = os.getenv(key, "").strip()
    return value or default


# --- 수집 대상 API ---------------------------------------------------------
# 베이스 URL은 환경변수로 분리하고, 쿼리 파라미터는 코드에서 조립한다.
OPEN_METEO_URL = _env("OPEN_METEO_URL", "https://api.open-meteo.com/v1/forecast")
COUNTRIES_URL = _env("COUNTRIES_URL", "https://countries.dev/alpha")
IP_API_URL = _env("IP_API_URL", "http://ip-api.com/json")

# --- 조회 파라미터 ---------------------------------------------------------
LATITUDE = float(_env("LATITUDE", "37.5665"))  # 서울 위도
LONGITUDE = float(_env("LONGITUDE", "126.9780"))  # 서울 경도
FORECAST_DAYS = int(_env("FORECAST_DAYS", "3"))
TIMEZONE = _env("TIMEZONE", "Asia/Seoul")
COUNTRY_CODE = _env("COUNTRY_CODE", "KOR")
TARGET_IP = _env("TARGET_IP", "8.8.8.8")

# --- 네트워크 설정 ---------------------------------------------------------
TIMEOUT_SECONDS = float(_env("TIMEOUT_SECONDS", "10"))
MAX_RETRIES = int(_env("MAX_RETRIES", "2"))


def build_api_targets() -> dict[str, tuple[str, dict[str, str | int | float]]]:
    """수집 대상별 (URL, 쿼리 파라미터) 를 만들어 반환한다.

    파라미터를 문자열로 이어 붙이지 않고 httpx 의 params 로 넘겨
    인코딩 실수를 방지한다.
    """
    return {
        "weather": (
            OPEN_METEO_URL,
            {
                "latitude": LATITUDE,
                "longitude": LONGITUDE,
                "hourly": "temperature_2m,precipitation_probability",
                "forecast_days": FORECAST_DAYS,
                "timezone": TIMEZONE,
            },
        ),
        "country": (f"{COUNTRIES_URL}/{COUNTRY_CODE}", {}),
        "ipinfo": (f"{IP_API_URL}/{TARGET_IP}", {}),
    }
