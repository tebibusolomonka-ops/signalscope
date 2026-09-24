import logging
import re
import time
import uuid

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

request_logger = logging.getLogger("signalscope.api.requests")

REQUEST_ID_HEADER = "X-Request-ID"
# Short values with simple characters only, so a client ID is safe to log and send back.
REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,64}")


class RequestIDMiddleware:
    """Give each HTTP request an ID and send it back in the X-Request-ID header.

    A usable ID from the client is kept. Otherwise a new UUID is used. Route
    code can read the ID from request.state.request_id.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        request_id = request.headers.get(REQUEST_ID_HEADER, "")
        if not REQUEST_ID_PATTERN.fullmatch(request_id):
            request_id = str(uuid.uuid4())
        request.state.request_id = request_id

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        await self.app(scope, receive, send_with_request_id)


class RequestLoggingMiddleware:
    """Log one line per HTTP request with method, path, status, duration and request ID.

    Needs to run inside RequestIDMiddleware.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = Request(scope).state.request_id
        start = time.monotonic()
        # Stays 500 when the app raises before it sends a response.
        status_code = 500

        async def send_and_record_status(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_and_record_status)
        finally:
            duration_ms = (time.monotonic() - start) * 1000
            # The query string is left out because it can contain tokens.
            request_logger.info(
                "%s %s %d %.1fms request_id=%s",
                scope["method"],
                scope["path"],
                status_code,
                duration_ms,
                request_id,
            )
