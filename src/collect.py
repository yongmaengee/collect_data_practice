"""
비동기 수집 모듈.

asyncio + httpx 를 사용해 3개의 공개 API를 asyncio.gather() 로 동시에 수집한다.
- Open-Meteo : 서울 3일 시간대별 기온·강수확률
- Countries.dev : 한국(KOR) 국가 정보
- ip-api : IP(8.8.8.8) 기반 지역 정보
"""

from __future__ import annotations

import asyncio
import random
import time
from typing import Any

import httpx

from src.config import MAX_RETRIES, TIMEOUT_SECONDS, build_api_targets

# 429(호출 제한) 발생 시 첫 재시도까지의 기본 대기 시간(초).
# 이후 지수적으로 늘어난다: 4s -> 8s -> 16s
RATE_LIMIT_BASE_DELAY = 4.0


def _retry_delay(attempt: int, error: Exception) -> float:
    """재시도까지 기다릴 시간(초)을 계산한다.

    - 429(Too Many Requests): 호출 제한이므로 짧은 대기로는 풀리지 않는다.
      서버가 Retry-After 헤더로 대기 시간을 알려주면 그 값을 따르고,
      없으면 지수 백오프(4s → 8s → 16s ...)로 충분히 물러난다.
    - 그 외 일시적 오류: 짧은 지수 백오프(0.5s → 1.0s ...)로 빠르게 재시도한다.

    지터(무작위 가산)를 더해 여러 요청의 재시도가 같은 시각에 몰리는 것을 막는다.
    """
    if isinstance(error, httpx.HTTPStatusError) and error.response.status_code == 429:
        retry_after = error.response.headers.get("Retry-After")
        if retry_after and retry_after.isdigit():
            return float(retry_after)  # 서버가 지정한 대기 시간을 우선한다
        return RATE_LIMIT_BASE_DELAY * (2**attempt) + random.uniform(0, 1)

    return 0.5 * (attempt + 1) + random.uniform(0, 0.3)


async def fetch_json(
    client: httpx.AsyncClient,
    name: str,
    url: str,
    params: dict[str, Any] | None = None,
    retries: int = MAX_RETRIES,
) -> dict[str, Any]:
    """단일 API를 호출해 JSON을 반환한다.

    일시적인 네트워크 오류에 대비해 최대 `retries` 회까지 재시도한다.
    오류 종류에 따라 대기 시간을 다르게 두며(_retry_delay 참고),
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
            # 429 는 코드 결함이 아니라 호출 제한이므로 메시지를 구분해 보여준다
            reason = (
                "호출 제한(429)"
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429
                else type(exc).__name__
            )
            print(f"[수집 실패] {name:<8} attempt={attempt + 1}/{retries + 1} 원인={reason}")

            if attempt < retries:
                delay = _retry_delay(attempt, exc)
                print(f"           {delay:.1f}초 후 재시도")
                await asyncio.sleep(delay)

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
