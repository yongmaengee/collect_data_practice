"""스키마 검증 테스트.

네트워크에 의존하지 않도록 고정된 샘플 JSON(fixture)으로 검증한다.
정상 케이스뿐 아니라 타입·범위 오류가 실제로 걸러지는지도 확인한다.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from src.models import (
    CountryInfo,
    IpInfo,
    WeatherHour,
    parse_country,
    parse_ipinfo,
    parse_weather,
)

# --- 테스트용 샘플 응답 (실제 API 응답 구조를 축약) ------------------------

SAMPLE_WEATHER = {
    "hourly": {
        "time": ["2026-08-03T00:00", "2026-08-03T01:00", "2026-08-03T02:00"],
        "temperature_2m": [25.3, 24.9, 24.5],
        "precipitation_probability": [0, 10, 35],
    }
}

SAMPLE_COUNTRY = {
    "name": "Korea (Republic of)",
    "alpha3Code": "KOR",
    "capital": "Seoul",
    "region": "Asia",
    "population": 51780579,
    "area": 100210,
    "latlng": [37, 127.5],
    "currencies": [{"code": "KRW", "name": "South Korean won"}],
    "languages": [{"name": "Korean", "iso639_1": "ko"}],
}

SAMPLE_IPINFO = {
    "status": "success",
    "query": "8.8.8.8",
    "country": "United States",
    "countryCode": "US",
    "regionName": "Virginia",
    "city": "Ashburn",
    "lat": 39.03,
    "lon": -77.5,
    "timezone": "America/New_York",
    "isp": "Google LLC",
}


# --- 정상 케이스 ------------------------------------------------------------


def test_parse_weather_정상() -> None:
    """시간대별 데이터가 행 단위로 변환되고 타입이 맞게 캐스팅된다."""
    records, errors = parse_weather(SAMPLE_WEATHER)

    assert errors == []
    assert len(records) == 3
    # ISO8601 문자열이 datetime 으로 변환되어야 한다
    assert records[0].time == datetime(2026, 8, 3, 0, 0)
    assert records[0].temperature_2m == 25.3
    assert records[2].precipitation_probability == 35


def test_parse_country_정상() -> None:
    """중첩 구조(latlng, currencies, languages)에서 대표값이 추출된다."""
    country, errors = parse_country(SAMPLE_COUNTRY)

    assert errors == []
    assert country is not None
    assert country.alpha3_code == "KOR"
    assert country.capital == "Seoul"
    assert country.latitude == 37.0
    assert country.currency_code == "KRW"
    assert country.language == "Korean"


def test_parse_ipinfo_정상() -> None:
    """camelCase 별칭이 snake_case 속성으로 매핑된다."""
    ipinfo, errors = parse_ipinfo(SAMPLE_IPINFO)

    assert errors == []
    assert ipinfo is not None
    assert ipinfo.country_code == "US"  # countryCode -> country_code
    assert ipinfo.region_name == "Virginia"  # regionName -> region_name
    assert ipinfo.longitude == -77.5  # lon -> longitude


# --- 범위·타입 검증 실패 케이스 ---------------------------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("temperature_2m", 999),  # 상한(60) 초과
        ("temperature_2m", -100),  # 하한(-60) 미만
        ("precipitation_probability", 150),  # 확률 100% 초과
        ("precipitation_probability", -1),  # 음수 확률
    ],
)
def test_weather_범위_위반시_예외(field: str, value: float) -> None:
    """범위를 벗어난 값은 ValidationError 로 걸러진다."""
    payload = {
        "time": "2026-08-03T00:00",
        "temperature_2m": 25.0,
        "precipitation_probability": 0,
    }
    payload[field] = value

    with pytest.raises(ValidationError):
        WeatherHour(**payload)


def test_weather_타입_오류시_예외() -> None:
    """숫자로 변환할 수 없는 문자열은 타입 오류로 걸러진다."""
    with pytest.raises(ValidationError):
        WeatherHour(
            time="2026-08-03T00:00",
            temperature_2m="더움",  # 숫자가 아님
            precipitation_probability=0,
        )


def test_ipinfo_조회실패_상태는_거부() -> None:
    """status 가 'success' 가 아니면 Literal 제약에 걸린다."""
    payload = {**SAMPLE_IPINFO, "status": "fail"}
    ipinfo, errors = parse_ipinfo(payload)

    assert ipinfo is None
    assert len(errors) == 1


def test_country_필드_누락시_예외처리() -> None:
    """필수 필드가 없어도 예외가 새어나가지 않고 오류 목록으로 반환된다."""
    payload = {key: value for key, value in SAMPLE_COUNTRY.items() if key != "population"}
    country, errors = parse_country(payload)

    assert country is None
    assert len(errors) == 1
    assert "country" in errors[0]


def test_country_음수_인구는_거부() -> None:
    """population 은 gt=0 제약이 걸려 있다."""
    with pytest.raises(ValidationError):
        CountryInfo(
            name="Test",
            alpha3Code="TST",
            capital="C",
            region="R",
            population=-1,  # 음수 인구는 불가능
            area=100,
            latitude=0,
            longitude=0,
            currency_code="TTT",
            language="L",
        )


def test_ipinfo_위도_범위_초과는_거부() -> None:
    """위도는 -90~90 범위를 벗어날 수 없다."""
    with pytest.raises(ValidationError):
        IpInfo(**{**SAMPLE_IPINFO, "lat": 120.0})


# --- 부분 실패 허용 동작 ----------------------------------------------------


def test_weather_일부만_깨져도_나머지는_통과() -> None:
    """한 시간대가 잘못돼도 정상 레코드는 살아남고 오류만 기록된다."""
    payload = {
        "hourly": {
            "time": ["2026-08-03T00:00", "2026-08-03T01:00"],
            "temperature_2m": [25.3, 999],  # 두 번째가 범위 초과
            "precipitation_probability": [0, 10],
        }
    }
    records, errors = parse_weather(payload)

    assert len(records) == 1  # 정상 1건은 살아남는다
    assert len(errors) == 1
    assert "weather[1]" in errors[0]


def test_weather_배열_길이_불일치_경고() -> None:
    """열 배열 길이가 어긋나면 짧은 쪽 기준으로 자르고 경고를 남긴다."""
    payload = {
        "hourly": {
            "time": ["2026-08-03T00:00", "2026-08-03T01:00"],
            "temperature_2m": [25.3],  # 1건뿐
            "precipitation_probability": [0, 10],
        }
    }
    records, errors = parse_weather(payload)

    assert len(records) == 1
    assert any("길이 불일치" in message for message in errors)


def test_weather_hourly_없으면_빈결과() -> None:
    """예상과 다른 응답이 와도 예외 대신 오류 메시지를 반환한다."""
    records, errors = parse_weather({"error": True})

    assert records == []
    assert len(errors) == 1
