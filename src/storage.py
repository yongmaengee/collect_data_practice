"""저장 및 성능 비교 모듈.

검증을 통과한 데이터를 CSV / Parquet 두 형식으로 저장하고
쓰기·읽기 시간과 파일 크기를 측정해 비교한다.

측정 대상 데이터가 작으면(72행) 시간 차이가 측정 오차에 묻히므로,
같은 작업을 여러 번 반복해 평균을 내고 필요하면 행을 복제해 규모별로도 비교한다.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from src.config import DATA_DIR

# 기본 반복 횟수 (한 번만 재면 편차가 커서 비교가 무의미해진다)
DEFAULT_REPEAT = 5


@dataclass
class BenchmarkResult:
    """한 형식(CSV 또는 Parquet)에 대한 측정 결과."""

    format_name: str
    rows: int
    write_seconds: float  # 반복 측정 평균
    read_seconds: float  # 반복 측정 평균
    file_bytes: int

    @property
    def file_kb(self) -> float:
        return self.file_bytes / 1024


def _measure(action, repeat: int) -> float:
    """action 을 repeat 회 실행하고 1회당 평균 소요 시간(초)을 돌려준다.

    time.perf_counter() 는 시스템 시계 변경에 영향받지 않는 고해상도 타이머라
    벤치마크에 적합하다.

    첫 호출에는 라이브러리 임포트·초기화 비용(특히 pyarrow)이 섞여 들어가
    실제 I/O 성능을 왜곡한다. 따라서 측정 전에 1회 예열(warm-up)을 실행한다.
    """
    action()  # 예열: 결과를 버리고 초기화 비용만 털어낸다

    started = time.perf_counter()
    for _ in range(repeat):
        action()
    return (time.perf_counter() - started) / repeat


def benchmark_csv(frame: pd.DataFrame, path: Path, repeat: int = DEFAULT_REPEAT) -> BenchmarkResult:
    """CSV 쓰기/읽기 성능을 측정한다."""
    write_seconds = _measure(lambda: frame.to_csv(path, index=False), repeat)
    read_seconds = _measure(lambda: pd.read_csv(path), repeat)
    return BenchmarkResult("CSV", len(frame), write_seconds, read_seconds, path.stat().st_size)


def benchmark_parquet(
    frame: pd.DataFrame, path: Path, repeat: int = DEFAULT_REPEAT
) -> BenchmarkResult:
    """Parquet 쓰기/읽기 성능을 측정한다 (엔진: pyarrow)."""
    write_seconds = _measure(lambda: frame.to_parquet(path, index=False, engine="pyarrow"), repeat)
    read_seconds = _measure(lambda: pd.read_parquet(path, engine="pyarrow"), repeat)
    return BenchmarkResult("Parquet", len(frame), write_seconds, read_seconds, path.stat().st_size)


def save_and_benchmark(
    frame: pd.DataFrame,
    name: str = "dataset",
    output_dir: Path = DATA_DIR,
    repeat: int = DEFAULT_REPEAT,
) -> list[BenchmarkResult]:
    """데이터를 CSV·Parquet 양쪽으로 저장하고 성능 측정 결과를 반환한다."""
    output_dir.mkdir(parents=True, exist_ok=True)  # data/ 가 없으면 만든다

    results = [
        benchmark_csv(frame, output_dir / f"{name}.csv", repeat),
        benchmark_parquet(frame, output_dir / f"{name}.parquet", repeat),
    ]
    return results


def amplify(frame: pd.DataFrame, factor: int) -> pd.DataFrame:
    """행을 factor 배로 복제한다.

    소량 데이터에서는 파일 포맷 간 차이가 드러나지 않으므로,
    규모가 커질 때의 경향을 보기 위한 보조 측정용이다.
    """
    return pd.concat([frame] * factor, ignore_index=True)


def format_results(results: list[BenchmarkResult]) -> str:
    """측정 결과를 표 형태 문자열로 만든다."""
    lines = [
        f"{'형식':<9}{'행 수':>9}{'쓰기(ms)':>12}{'읽기(ms)':>12}{'크기(KB)':>12}",
        "-" * 54,
    ]
    for result in results:
        lines.append(
            f"{result.format_name:<9}{result.rows:>9,}"
            f"{result.write_seconds * 1000:>12.2f}"
            f"{result.read_seconds * 1000:>12.2f}"
            f"{result.file_kb:>12.1f}"
        )

    # CSV 대비 Parquet 의 상대 성능을 배수로 요약한다
    csv_result = next((r for r in results if r.format_name == "CSV"), None)
    parquet_result = next((r for r in results if r.format_name == "Parquet"), None)
    if csv_result and parquet_result and parquet_result.write_seconds > 0:
        write_ratio = csv_result.write_seconds / parquet_result.write_seconds
        read_ratio = csv_result.read_seconds / parquet_result.read_seconds
        size_ratio = csv_result.file_bytes / parquet_result.file_bytes
        lines.append(
            f"→ Parquet 대비 CSV: 쓰기 {write_ratio:.2f}배, "
            f"읽기 {read_ratio:.2f}배, 크기 {size_ratio:.2f}배"
        )
    return "\n".join(lines)
