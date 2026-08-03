"""
비동기 수집 모듈.

asyncio + httpx 를 사용해 3개의 공개 API를 asyncio.gather() 로 동시에 수집한다.
- Open-Meteo : 서울 3일 시간대별 기온·강수확률
- Countries.dev : 한국(KOR) 국가 정보
- ip-api : IP(8.8.8.8) 기반 지역 정보
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from src.config import MAX_RETRIES, TIMEOUT_SECONDS, build_api_targets


async def fetch_json(
    client: httpx.AsyncClient,
    name: str,
    url: str,
    params: dict[str, Any] | None = None,
    retries: int = MAX_RETRIES,
) -> dict[str, Any]:
    """단일 API를 호출해 JSON을 반환한다.

    일시적인 네트워크 오류에 대비해 최대 `retries` 회까지 재시도한다.
    최종 실패 시 예외를 그대로 올려 보내 상위(gather)에서 처리하게 한다.
    """
    last_error: Exception | None = None

    for attempt in range(retries + 1):
        try:
            started = time.perf_counter()
            response = await client.get(url, params=params)
            response.raise_for_status()  # 4xx / 5xx 는 예외로 처리
            elapsed = time.perf_counter() - started
            print(f"[수집 성공] {name:<8} status={response.status_code} {elapsed:.3f}s")
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:  # 통신 오류 + JSON 파싱 오류
            last_error = exc
            print(f"[수집 실패] {name:<8} attempt={attempt + 1}/{retries + 1} error={exc!r}")
            if attempt < retries:
                await asyncio.sleep(0.5 * (attempt + 1))  # 지수적 대기 후 재시도

    # 재시도까지 모두 실패한 경우
    raise RuntimeError(f"{name} 수집 실패: {last_error!r}")


async def collect_all() -> dict[str, Any]:
    """3개 API를 asyncio.gather() 로 동시에 수집한다.

    return_exceptions=True 로 두어 하나가 실패해도 나머지 결과는 살린다.
    반환값은 {api 이름: JSON 또는 Exception} 형태.
    """
    targets = build_api_targets()  # 설정(.env 또는 기본값)에서 URL·파라미터를 가져온다
    started = time.perf_counter()

    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
        tasks = [fetch_json(client, name, url, params) for name, (url, params) in targets.items()]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    elapsed = time.perf_counter() - started
    print(f"[동시 수집 완료] 총 {len(results)}건 / {elapsed:.3f}s")

    return dict(zip(targets.keys(), results, strict=True))


if __name__ == "__main__":
    # 단독 실행 시 수집 결과 요약만 출력해 응답 정상 여부를 확인한다.
    collected = asyncio.run(collect_all())
    for api_name, payload in collected.items():
        if isinstance(payload, Exception):
            print(f"{api_name:<8} -> 예외 발생: {payload!r}")
        else:
            print(f"{api_name:<8} -> top-level keys: {list(payload)[:6]}")
