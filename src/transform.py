"""변환 모듈.

검증을 통과한 3개 소스의 모델을 하나의 통합 테이블(넓은 형태)로 합친다.
weather(72행)를 기준 행으로 두고, country·ipinfo 는 모든 행에 공통으로 붙는
컨텍스트 컬럼으로 취급한다.

추후 정규화가 필요하면 split_frames() 로 소스별 3개 테이블로 다시 나눌 수 있다.
"""

from __future__ import annotations

import pandas as pd

from src.models import CountryInfo, IpInfo, WeatherHour

# 통합 테이블에서 각 소스가 담당하는 컬럼 (분리 시 그대로 재사용)
WEATHER_COLUMNS = ["time", "temperature_2m", "precipitation_probability"]
COUNTRY_COLUMNS = [
    "country_name",
    "country_alpha3",
    "country_capital",
    "country_region",
    "country_population",
    "country_area",
    "country_latitude",
    "country_longitude",
    "country_currency",
    "country_language",
]
IP_COLUMNS = [
    "ip_query",
    "ip_country",
    "ip_country_code",
    "ip_region",
    "ip_city",
    "ip_latitude",
    "ip_longitude",
    "ip_timezone",
    "ip_isp",
]


def build_unified_frame(
    weather: list[WeatherHour],
    country: CountryInfo | None,
    ipinfo: IpInfo | None,
) -> pd.DataFrame:
    """검증 통과 데이터를 하나의 DataFrame 으로 합친다.

    country·ipinfo 는 단일 레코드이므로 브로드캐스트되어 전 행에 동일한 값이 들어간다.
    (검증 실패로 None 인 경우 해당 컬럼은 결측치로 남겨 파이프라인을 계속 진행한다)
    """
    if not weather:
        # 기준이 되는 시계열이 없으면 빈 테이블을 반환한다
        return pd.DataFrame(columns=WEATHER_COLUMNS + COUNTRY_COLUMNS + IP_COLUMNS)

    # 모델 -> dict 변환 후 행 단위 테이블 생성
    frame = pd.DataFrame([record.model_dump() for record in weather])

    # 국가 정보 컬럼 (접두사 country_ 로 출처를 명시)
    frame["country_name"] = country.name if country else pd.NA
    frame["country_alpha3"] = country.alpha3_code if country else pd.NA
    frame["country_capital"] = country.capital if country else pd.NA
    frame["country_region"] = country.region if country else pd.NA
    frame["country_population"] = country.population if country else pd.NA
    frame["country_area"] = country.area if country else pd.NA
    frame["country_latitude"] = country.latitude if country else pd.NA
    frame["country_longitude"] = country.longitude if country else pd.NA
    frame["country_currency"] = country.currency_code if country else pd.NA
    frame["country_language"] = country.language if country else pd.NA

    # IP 지역 정보 컬럼 (접두사 ip_)
    frame["ip_query"] = ipinfo.query if ipinfo else pd.NA
    frame["ip_country"] = ipinfo.country if ipinfo else pd.NA
    frame["ip_country_code"] = ipinfo.country_code if ipinfo else pd.NA
    frame["ip_region"] = ipinfo.region_name if ipinfo else pd.NA
    frame["ip_city"] = ipinfo.city if ipinfo else pd.NA
    frame["ip_latitude"] = ipinfo.latitude if ipinfo else pd.NA
    frame["ip_longitude"] = ipinfo.longitude if ipinfo else pd.NA
    frame["ip_timezone"] = ipinfo.timezone if ipinfo else pd.NA
    frame["ip_isp"] = ipinfo.isp if ipinfo else pd.NA

    return frame


def split_frames(frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """통합 테이블을 소스별 3개 테이블로 되돌린다(정규화).

    country·ipinfo 는 모든 행에 반복되는 값이므로 중복을 제거해 1행으로 줄인다.
    """
    return {
        "weather": frame[WEATHER_COLUMNS].copy(),
        "country": frame[COUNTRY_COLUMNS].drop_duplicates().reset_index(drop=True),
        "ipinfo": frame[IP_COLUMNS].drop_duplicates().reset_index(drop=True),
    }
