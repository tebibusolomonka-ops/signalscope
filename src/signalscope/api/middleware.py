import logging
import re
import time
import uuid
from contextlib import suppress

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


PAYLOAD_TOO_LARGE = (
    b'{"error":{"code":"payload_too_large","message":"The request body is too large."}}'
)


class RequestBodyTooLarge(Exception):
    pass


class RequestSizeLimitMiddleware:
    """Reject oversized request bodies with 413, before the route reads them.

    JSON requests use the smaller JSON limit; other bodies, such as binary
    uploads and organization archives, use the larger upload limit. The declared
    Content-Length is checked before the route reads the body, so an oversized
    request is rejected without being buffered. Routes keep their own, tighter
    checks (streamed file size, inner archive member limits).
    """

    def __init__(self, app: ASGIApp, max_json_bytes: int, max_upload_bytes: int) -> None:
        self.app = app
        self.max_json_bytes = max_json_bytes
        self.max_upload_bytes = max_upload_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        length = headers.get(b"content-length")
        content_type = headers.get(b"content-type", b"")
        limit = (
            self.max_json_bytes
            if content_type.startswith(b"application/json")
            else self.max_upload_bytes
        )
        if length is not None and length.isdigit() and int(length) > limit:
            await _send_payload_too_large(send)
            return

        received = 0
        rejected = False

        async def receive_with_limit() -> Message:
            nonlocal received, rejected
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    rejected = True
                    await _send_payload_too_large(send)
                    raise RequestBodyTooLarge
            return message

        async def send_unless_rejected(message: Message) -> None:
            if not rejected:
                await send(message)

        with suppress(RequestBodyTooLarge):
            await self.app(scope, receive_with_limit, send_unless_rejected)


async def _send_payload_too_large(send: Send) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(PAYLOAD_TOO_LARGE)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": PAYLOAD_TOO_LARGE})


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": (
        "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
        "magnetometer=(), microphone=(), payment=(), usb=()"
    ),
}


class SecurityHeadersMiddleware:
    """Add safe HTTP security headers to every response, including API errors.

    Values a route already set are kept, so a route can override a default. The
    headers are harmless for the same-origin React app and the JSON API. When a
    content security policy is given, it is added as Content-Security-Policy.
    """

    def __init__(self, app: ASGIApp, content_security_policy: str | None = None) -> None:
        self.app = app
        self.headers = dict(SECURITY_HEADERS)
        if content_security_policy:
            self.headers["Content-Security-Policy"] = content_security_policy

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_security_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in self.headers.items():
                    if name not in headers:
                        headers[name] = value
            await send(message)

        await self.app(scope, receive, send_with_security_headers)


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
