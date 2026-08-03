"""파이프라인 진입점.

수집(비동기) -> 검증(Pydantic v2) -> 변환(통합 테이블) -> 저장·성능 비교(CSV/Parquet)
전체 흐름을 순서대로 실행하고 결과를 콘솔에 출력한다.

실행: python -m src.main
"""

from __future__ import annotations

import asyncio

from src.collect import collect_all
from src.config import DATA_DIR
from src.models import parse_country, parse_ipinfo, parse_weather
from src.storage import amplify, format_results, save_and_benchmark
from src.transform import build_unified_frame, split_frames

# 규모별 경향을 보기 위한 복제 배수 (72행 -> 72,000행)
AMPLIFY_FACTOR = 1000


def print_header(title: str) -> None:
    """단계 구분용 제목을 출력한다."""
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


async def run_pipeline() -> None:
    """전체 파이프라인을 순서대로 실행한다."""

    # --- 1) 비동기 수집 ---------------------------------------------------
    print_header("1. 비동기 수집 (asyncio.gather)")
    raw = await collect_all()

    # 수집 자체가 실패한 소스는 검증 단계로 넘기지 않는다
    failed = {name: result for name, result in raw.items() if isinstance(result, Exception)}
    for name, error in failed.items():
        print(f"[경고] {name} 수집 실패 -> 해당 데이터는 제외하고 진행: {error!r}")

    # --- 2) 스키마 검증 ---------------------------------------------------
    print_header("2. 스키마 검증 (Pydantic v2)")
    all_errors: list[str] = []

    weather_records, weather_errors = (
        parse_weather(raw["weather"]) if "weather" not in failed else ([], ["weather: 수집 실패"])
    )
    country_record, country_errors = (
        parse_country(raw["country"]) if "country" not in failed else (None, ["country: 수집 실패"])
    )
    ip_record, ip_errors = (
        parse_ipinfo(raw["ipinfo"]) if "ipinfo" not in failed else (None, ["ipinfo: 수집 실패"])
    )
    all_errors.extend(weather_errors + country_errors + ip_errors)

    print(f"weather : {len(weather_records)}건 검증 통과")
    print(f"country : {'통과' if country_record else '실패'}")
    print(f"ipinfo  : {'통과' if ip_record else '실패'}")
    if all_errors:
        print(f"\n검증 오류 {len(all_errors)}건:")
        for message in all_errors[:10]:  # 너무 길어지지 않게 상위 10건만
            print(f"  - {message}")
    else:
        print("검증 오류 없음")

    if not weather_records:
        # 기준 시계열이 없으면 저장할 데이터가 없으므로 중단한다
        print("\n[중단] 검증을 통과한 데이터가 없어 저장 단계를 건너뜁니다.")
        return

    # --- 3) 통합 테이블 생성 ----------------------------------------------
    print_header("3. 통합 데이터셋 생성")
    frame = build_unified_frame(weather_records, country_record, ip_record)
    print(f"shape: {frame.shape[0]}행 × {frame.shape[1]}열")
    print(f"컬럼: {list(frame.columns)}")
    print("\n[미리보기]")
    print(frame.head(3).to_string())

    # --- 4) 저장 및 성능 비교 ---------------------------------------------
    print_header("4. 저장 및 성능 비교 (CSV vs Parquet)")
    results = save_and_benchmark(frame, name="dataset")
    print(format_results(results))

    # 소량 데이터에서는 차이가 작으므로 규모를 키워 경향을 함께 확인한다
    print(f"\n[참고] 행을 {AMPLIFY_FACTOR}배로 복제한 대용량 비교")
    large_frame = amplify(frame, AMPLIFY_FACTOR)
    large_results = save_and_benchmark(large_frame, name="dataset_large", repeat=3)
    print(format_results(large_results))

    # --- 5) 정규화 분리 (참고) --------------------------------------------
    print_header("5. 소스별 테이블 분리 (참고)")
    for table_name, table in split_frames(frame).items():
        print(f"{table_name:<9} {table.shape[0]:>5}행 × {table.shape[1]}열")

    print(f"\n저장 위치: {DATA_DIR}")


if __name__ == "__main__":
    asyncio.run(run_pipeline())
