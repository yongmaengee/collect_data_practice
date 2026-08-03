"""스키마 검증 모듈.

수집한 JSON에서 필요한 필드만 추출해 Pydantic v2 모델로 타입·범위를 검증한다.
검증에 실패한 레코드는 예외를 잡아 건너뛰고, 사유를 함께 모아 반환한다.
(하나가 깨져도 파이프라인 전체가 멈추지 않게 하기 위함)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class WeatherHour(BaseModel):
    """Open-Meteo 시간대별 예보 1건 (기온·강수확률)."""

    # extra="forbid": 정의하지 않은 필드가 들어오면 오류로 잡아 스키마 변화를 조기에 감지
    model_config = ConfigDict(extra="forbid")

    time: datetime  # "2026-08-03T00:00" 형태의 ISO8601 문자열을 datetime 으로 변환
    temperature_2m: float = Field(ge=-60, le=60, description="지상 2m 기온(℃)")
    precipitation_probability: int = Field(ge=0, le=100, description="강수확률(%)")


class CountryInfo(BaseModel):
    """Countries.dev 국가 정보 (필요한 필드만 추출)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str
    # JSON 의 camelCase 키를 snake_case 파이썬 속성으로 매핑
    alpha3_code: str = Field(alias="alpha3Code", min_length=3, max_length=3)
    capital: str
    region: str
    population: int = Field(gt=0, description="인구 수")
    area: float = Field(gt=0, description="면적(km²)")
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    currency_code: str = Field(min_length=3, max_length=3)
    language: str

    @field_validator("alpha3_code", "currency_code")
    @classmethod
    def to_upper(cls, value: str) -> str:
        """국가·통화 코드는 대문자로 통일한다."""
        return value.upper()


class IpInfo(BaseModel):
    """ip-api IP 기반 지역 정보."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    # status 가 "success" 가 아니면 조회 실패이므로 Literal 로 강제한다
    status: Literal["success"]
    query: str = Field(description="조회한 IP 주소")
    country: str
    country_code: str = Field(alias="countryCode", min_length=2, max_length=2)
    region_name: str = Field(alias="regionName")
    city: str
    latitude: float = Field(alias="lat", ge=-90, le=90)
    longitude: float = Field(alias="lon", ge=-180, le=180)
    timezone: str
    isp: str


# --- 원본 JSON -> 모델 변환 ------------------------------------------------


def parse_weather(payload: dict[str, Any]) -> tuple[list[WeatherHour], list[str]]:
    """Open-Meteo 응답의 컬럼형 hourly 데이터를 시간별 레코드로 변환·검증한다.

    응답은 {"time": [...], "temperature_2m": [...], ...} 처럼 열 단위로 오므로
    zip 으로 행 단위(레코드)로 바꾼 뒤 한 건씩 검증한다.

    Returns:
        (검증 통과 레코드 목록, 오류 메시지 목록)
    """
    hourly = payload.get("hourly")
    if not isinstance(hourly, dict):
        return [], ["weather: 응답에 'hourly' 필드가 없습니다"]

    times = hourly.get("time", [])
    temps = hourly.get("temperature_2m", [])
    probs = hourly.get("precipitation_probability", [])

    # 세 배열의 길이가 다르면 데이터가 어긋난 것이므로 짧은 쪽 기준으로 자르고 경고한다
    errors: list[str] = []
    length = min(len(times), len(temps), len(probs))
    if not (len(times) == len(temps) == len(probs)):
        errors.append(
            f"weather: 배열 길이 불일치 "
            f"(time={len(times)}, temp={len(temps)}, prob={len(probs)}) -> {length}건만 사용"
        )

    records: list[WeatherHour] = []
    for index in range(length):
        try:
            records.append(
                WeatherHour(
                    time=times[index],
                    temperature_2m=temps[index],
                    precipitation_probability=probs[index],
                )
            )
        except ValidationError as exc:
            # 한 시간대가 깨져도 나머지는 살린다
            first_message = exc.errors()[0]["msg"]
            errors.append(f"weather[{index}]: {exc.error_count()}건 오류 - {first_message}")

    return records, errors


def parse_country(payload: dict[str, Any]) -> tuple[CountryInfo | None, list[str]]:
    """국가 정보 응답에서 필요한 필드만 뽑아 검증한다."""
    try:
        latlng = payload.get("latlng") or [None, None]
        currencies = payload.get("currencies") or [{}]
        languages = payload.get("languages") or [{}]

        country = CountryInfo(
            name=payload["name"],
            alpha3Code=payload["alpha3Code"],
            capital=payload["capital"],
            region=payload["region"],
            population=payload["population"],
            area=payload["area"],
            latitude=latlng[0],
            longitude=latlng[1],
            # 중첩 배열에서 대표값(첫 번째)만 추출한다
            currency_code=currencies[0].get("code"),
            language=languages[0].get("name"),
        )
        return country, []
    except (ValidationError, KeyError, IndexError, TypeError) as exc:
        # 필드 누락(KeyError)·타입 오류(ValidationError) 모두 여기서 흡수한다
        return None, [f"country: 검증 실패 - {exc!r}"]


def parse_ipinfo(payload: dict[str, Any]) -> tuple[IpInfo | None, list[str]]:
    """IP 지역 정보 응답에서 필요한 필드만 뽑아 검증한다."""
    try:
        # 필요한 키만 골라 넘긴다 (extra="forbid" 이므로 불필요한 키는 제외해야 함)
        wanted = ("status", "query", "country", "countryCode", "regionName", "city",
                  "lat", "lon", "timezone", "isp")
        return IpInfo(**{key: payload.get(key) for key in wanted}), []
    except (ValidationError, TypeError) as exc:
        return None, [f"ipinfo: 검증 실패 - {exc!r}"]
