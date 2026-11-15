"""In-memory cache of API answers (issue #8; ADR 0005: indexes first, then this, no Redis).

An answer depends only on the rows stored in the database, and those rows change only
through the import, so every GET under /api/ is cached by its full URL and the whole
cache is cleared whenever the import runs (backend/importer/services.py). A miss answers
exactly like without the cache; the answer is then stored for the next request.
"""

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

# Enough for every sensor, road, granularity and window of the dashboard; when full, the
# oldest entry leaves (insertion order is kept by the dict, so that is its first key).
MAX_ENTRIES = 256

_answers: dict[str, bytes] = {}


def clear() -> None:
    """Forget every cached answer; the import calls this after it wrote new rows."""
    _answers.clear()


class ResponseCacheMiddleware(BaseHTTPMiddleware):
    """Serve a cached answer instead of running the query and building the response again."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        if request.method != "GET" or not path.startswith("/api/") or path == "/api/health":
            return await call_next(request)
        key = str(request.url)
        cached = _answers.get(key)
        if cached is not None:
            return Response(content=cached, media_type="application/json")
        response = await call_next(request)
        # call_next answers with a streamed response of one pass over the body: read it
        # through and serve the read bytes onwards as an ordinary answer.
        if response.status_code != 200:
            return response
        content_type = response.headers.get("content-type", "")
        if not content_type.startswith("application/json"):
            return response
        body = b"".join([chunk async for chunk in response.body_iterator])
        _answers[key] = body
        while len(_answers) > MAX_ENTRIES:
            _answers.pop(next(iter(_answers)))
        return Response(content=body, status_code=200, headers=dict(response.headers))
