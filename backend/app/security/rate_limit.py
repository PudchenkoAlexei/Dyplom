import asyncio
from collections import defaultdict, deque
from time import monotonic

from fastapi import HTTPException, Request, status

_attempts: dict[str, deque[float]] = defaultdict(deque)
_lock = asyncio.Lock()


def _client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",", maxsplit=1)[0].strip()
    return request.client.host if request.client else "unknown"


def _normalize_identifier(value: str) -> str:
    return " ".join(value.casefold().split()) or "unknown"


async def check_rate_limit(
    request: Request,
    *,
    scope: str,
    identifier: str,
    limit: int,
    window_seconds: int,
) -> None:
    key = f"{scope}:{_client_ip(request)}:{_normalize_identifier(identifier)}"
    now = monotonic()
    window_start = now - window_seconds

    async with _lock:
        bucket = _attempts[key]
        while bucket and bucket[0] < window_start:
            bucket.popleft()

        if len(bucket) >= limit:
            retry_after = max(1, int(window_seconds - (now - bucket[0])) + 1)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many attempts. Please try again later.",
                headers={"Retry-After": str(retry_after)},
            )

        bucket.append(now)
