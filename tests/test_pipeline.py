"""수집·변환·저장 테스트.

실제 API를 호출하면 테스트가 네트워크 상태에 따라 흔들리므로,
httpx.MockTransport 로 응답을 가짜로 만들어 로직만 검증한다.
"""

from __future__ import annotations

import httpx
import pandas as pd
import pytest

from src.collect import fetch_json
from src.models import parse_country, parse_ipinfo, parse_weather
from src.storage import save_and_benchmark
from src.transform import build_unified_frame, split_frames
from tests.test_models import SAMPLE_COUNTRY, SAMPLE_IPINFO, SAMPLE_WEATHER

# --- 수집 ------------------------------------------------------------------


async def test_fetch_json_정상응답() -> None:
    """200 응답이면 JSON 을 그대로 파싱해 반환한다."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await fetch_json(client, "test", "http://example.test")

    assert result == {"ok": True}


async def test_fetch_json_실패시_재시도후_예외() -> None:
    """계속 500이 오면 재시도 후 RuntimeError 로 감싸서 올린다."""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RuntimeError):
            await fetch_json(client, "test", "http://example.test", retries=1)

    assert call_count == 2  # 최초 1회 + 재시도 1회


# --- 변환 ------------------------------------------------------------------


def _build_sample_frame() -> pd.DataFrame:
    """샘플 응답으로 통합 테이블을 만든다."""
    weather, _ = parse_weather(SAMPLE_WEATHER)
    country, _ = parse_country(SAMPLE_COUNTRY)
    ipinfo, _ = parse_ipinfo(SAMPLE_IPINFO)
    return build_unified_frame(weather, country, ipinfo)


def test_통합테이블_형태() -> None:
    """weather 행 수만큼 생성되고 country·ip 값이 전 행에 붙는다."""
    frame = _build_sample_frame()

    assert len(frame) == 3  # 샘플 weather 3건
    assert frame["country_alpha3"].nunique() == 1  # 모든 행에 동일한 값
    assert frame["ip_city"].iloc[0] == "Ashburn"


def test_통합테이블_일부_소스_실패해도_생성() -> None:
    """country·ipinfo 가 없으면 결측치로 채우고 파이프라인은 계속된다."""
    weather, _ = parse_weather(SAMPLE_WEATHER)
    frame = build_unified_frame(weather, None, None)

    assert len(frame) == 3
    assert frame["country_name"].isna().all()


def test_weather_없으면_빈테이블() -> None:
    """기준 시계열이 없으면 컬럼만 있는 빈 테이블을 반환한다."""
    frame = build_unified_frame([], None, None)

    assert frame.empty


def test_테이블_분리() -> None:
    """통합 테이블을 소스별로 되돌리면 중복이 제거된다."""
    tables = split_frames(_build_sample_frame())

    assert len(tables["weather"]) == 3
    assert len(tables["country"]) == 1  # 반복 값은 1행으로 축약
    assert len(tables["ipinfo"]) == 1


# --- 저장 ------------------------------------------------------------------


def test_csv_parquet_저장_및_왕복(tmp_path) -> None:
    """두 형식 모두 파일이 생성되고, 읽어들인 결과가 원본과 일치한다."""
    frame = _build_sample_frame()
    results = save_and_benchmark(frame, name="test", output_dir=tmp_path, repeat=1)

    assert {result.format_name for result in results} == {"CSV", "Parquet"}
    assert all(result.file_bytes > 0 for result in results)

    # Parquet 은 타입 정보를 보존하므로 원본과 완전히 동일해야 한다
    restored = pd.read_parquet(tmp_path / "test.parquet")
    pd.testing.assert_frame_equal(restored, frame)
