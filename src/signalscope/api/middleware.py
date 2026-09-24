import re
import uuid

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

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
